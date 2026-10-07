package soc.core.ooo

import chisel3._
import chisel3.util._

/** One address-translation miss. The caller owns ordering, replay and TLB insertion. */
class SvWalkRequest extends Bundle {
    val virtualAddress = UInt(64.W)
    val rootPpn        = UInt(44.W)
    val mode           = UInt(4.W) // satp.MODE: Bare=0, Sv39=8, Sv48=9, Sv57=10.
    val privilege      = UInt(2.W) // Effective privilege, after MPRV for data accesses.
    val access         = UInt(2.W) // PmpAccess encoding.
    val sum            = Bool()
    val mxr            = Bool()
}

class SvWalkResponse extends Bundle {
    val physicalAddress = UInt(64.W)
    val pageFault       = Bool()
    val accessFault     = Bool()
    val level           = UInt(3.W)
    val napot           = Bool()
    val global          = Bool()
    val pbmt            = UInt(2.W)
}

class SvPteReadResult extends Bundle {
    val data  = UInt(64.W)
    val error = Bool() // Includes PMA and downstream bus errors.
}

class SvPteReadPort extends Bundle {
    val request  = Decoupled(UInt(64.W))
    val response = Flipped(Decoupled(new SvPteReadResult))
}

/** Parameterized RV64 page-table walk. One walk in flight, one eight-byte PTE read at a time.
  * Instantiate independent I/D walkers for concurrent misses; arbitration is outside this block.
  * Svade is used: missing A/D raises a page fault and never writes the PTE.
  */
class SvPageTableWalker(maxLevels: Int = 4, pmpEntries: Int = 16) extends Module {
    require(Set(3, 4, 5).contains(maxLevels))
    require(Set(0, 8, 16).contains(pmpEntries))
    val io = IO(new Bundle {
        val start    = Flipped(Decoupled(new SvWalkRequest))
        val complete = Decoupled(new SvWalkResponse)
        val memory   = new SvPteReadPort
        val pmpState = Input(new PmpState)
    })
    val idle :: issue :: awaitPte :: finish :: Nil = Enum(4)
    val state   = RegInit(idle)
    val walk    = Reg(new SvWalkRequest)
    val result  = RegInit(0.U.asTypeOf(new SvWalkResponse))
    val table   = Reg(UInt(44.W))
    val level   = Reg(UInt(3.W))
    val global  = RegInit(false.B)
    val vpn     = Wire(Vec(maxLevels, UInt(9.W)))
    for (i <- 0 until maxLevels) { vpn(i) := walk.virtualAddress(12 + 9 * i + 8, 12 + 9 * i) }
    val pteAddress = Cat(table, 0.U(12.W)) + (vpn(level(log2Ceil(maxLevels) - 1, 0)) << 3)
    val pmp = Module(new PmpChecker(pmpEntries))
    pmp.io.state     := io.pmpState
    pmp.io.address   := pteAddress
    pmp.io.size      := 3.U
    pmp.io.privilege := 1.U // Implicit page-table reads use S-mode physical permissions.
    pmp.io.access    := PmpAccess.read

    io.start.ready          := state === idle
    io.complete.valid       := state === finish
    io.complete.bits        := result
    // A one-entry, non-flow-through queue registers the PMP-approved PTE read.
    // It breaks the walker-to-shared-memory combinational path and adds one cycle
    // per PTE read, without changing the common TLB-hit path.
    val pendingRead = Module(new Queue(UInt(64.W), 1, pipe = false, flow = false))
    pendingRead.io.enq.valid := state === issue && !pmp.io.denied
    pendingRead.io.enq.bits  := pteAddress
    io.memory.request.valid := pendingRead.io.deq.valid
    io.memory.request.bits  := pendingRead.io.deq.bits
    pendingRead.io.deq.ready := io.memory.request.ready
    io.memory.response.ready := state === awaitPte

    when(io.start.fire) {
        walk   := io.start.bits
        result := 0.U.asTypeOf(new SvWalkResponse)
        global := false.B
        val mode = io.start.bits.mode
        val configured = mode >= 8.U && mode <= (maxLevels + 5).U
        val levels = mode - 5.U
        val signBit = MuxLookup(mode, io.start.bits.virtualAddress(38))(Seq(
            9.U -> io.start.bits.virtualAddress(47),
            10.U -> io.start.bits.virtualAddress(56)
        ))
        val canonical = MuxLookup(mode, false.B)(
            Seq(
                8.U -> (io.start.bits.virtualAddress(63, 39) === Fill(25, signBit)),
                9.U -> (io.start.bits.virtualAddress(63, 48) === Fill(16, signBit)),
                10.U -> (io.start.bits.virtualAddress(63, 57) === Fill(7, signBit))
            ))
        when(mode === 0.U || io.start.bits.privilege === 3.U) {
            result.physicalAddress := io.start.bits.virtualAddress
            state := finish
        }.elsewhen(!configured || !canonical) {
            result.pageFault := true.B
            state := finish
        }.otherwise {
            table := io.start.bits.rootPpn
            level := levels - 1.U
            state := issue
        }
    }
    when(state === issue && pmp.io.denied) {
        result.accessFault := true.B
        state := finish
    }
    when(pendingRead.io.enq.fire) { state := awaitPte }
    when(io.memory.response.fire) {
        val pte     = io.memory.response.bits.data
        val leaf    = pte(1) || pte(3)
        val napot   = pte(63)
        val pbmt    = pte(62, 61)
        val ppn     = pte(53, 10)
        val invalid = !pte(0) || (pte(2) && !pte(1)) || pte(60, 54).orR ||
            pbmt === 3.U || (napot && (level =/= 0.U || !leaf || ppn(3, 0) =/= 8.U)) ||
            (!leaf && (pte(7, 6).orR || pte(4) || pbmt.orR || napot))
        val superpageMisaligned = (0 until maxLevels - 1).map(i =>
            level > i.U && ppn(9 * i + 8, 9 * i).orR).reduce(_ || _)
        val user = pte(4)
        val privilegeAllowed = Mux(walk.privilege === 0.U, user,
            Mux(walk.access === PmpAccess.execute, !user, !user || walk.sum))
        val permission = MuxLookup(walk.access, false.B)(Seq(
            PmpAccess.read -> (pte(1) || (walk.mxr && pte(3))),
            PmpAccess.write -> pte(2),
            PmpAccess.execute -> pte(3),
            PmpAccess.readWrite -> (pte(2) && (pte(1) || (walk.mxr && pte(3))))
        ))
        val dirtyNeeded = walk.access === PmpAccess.write || walk.access === PmpAccess.readWrite
        when(io.memory.response.bits.error) {
            result.accessFault := true.B
            state := finish
        }.elsewhen(invalid) {
            result.pageFault := true.B
            state := finish
        }.elsewhen(!leaf) {
            when(level === 0.U) {
                result.pageFault := true.B
                state := finish
            }.otherwise {
                table  := ppn
                level  := level - 1.U
                global := global || pte(5)
                state  := issue
            }
        }.elsewhen(superpageMisaligned || !privilegeAllowed || !permission || !pte(6) ||
            (dirtyNeeded && !pte(7))) {
            result.pageFault := true.B
            state := finish
        }.otherwise {
            var rebuilt: UInt = ppn
            for (i <- 0 until maxLevels - 1) {
                val keep = ((BigInt(1) << 44) - 1) ^ (BigInt(511) << (9 * i))
                rebuilt = Mux(level > i.U, (rebuilt & keep.U(44.W)) | (vpn(i) << (9 * i)), rebuilt)
            }
            val finalPpn = Mux(napot, Cat(rebuilt(43, 4), vpn(0)(3, 0)), rebuilt)
            result.physicalAddress := Cat(finalPpn, walk.virtualAddress(11, 0))
            result.level  := level
            result.napot  := napot
            result.global := global || pte(5)
            result.pbmt   := pbmt
            state := finish
        }
    }
    when(io.complete.fire) { state := idle }
}
