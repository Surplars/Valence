package soc.core.pipeline

import chisel3._
import chisel3.util._
import soc.isa.{MCause, PrivilegeLevel}
import soc.memory.{CacheReq, CacheResp}
import soc.memory.cache.CacheCmd

object Sv39AccessType extends ChiselEnum {
    val Load, Store, Fetch = Value
}

class Sv39WalkReq(XLEN: Int) extends Bundle {
    val vaddr = UInt(XLEN.W)
    val satp = UInt(XLEN.W)
    val access = Sv39AccessType()
    val priv = UInt(2.W)
    val mxr = Bool()
    val sum = Bool()
}

class Sv39WalkResp(XLEN: Int) extends Bundle {
    val paddr = UInt(XLEN.W)
    val fault = new MemoryFaultInfo(XLEN)
}

class Sv39PteTranslator(XLEN: Int = 64) extends Module {
    require(XLEN == 64, "Sv39PteTranslator currently targets RV64 Sv39 only")

    val io = IO(new Bundle {
        val valid = Input(Bool())
        val vaddr = Input(UInt(XLEN.W))
        val pte   = Input(UInt(XLEN.W))
        val level = Input(UInt(2.W))
        val access = Input(Sv39AccessType())
        val priv = Input(UInt(2.W))
        val mxr = Input(Bool())
        val sum = Input(Bool())

        val leaf = Output(Bool())
        val paddr = Output(UInt(XLEN.W))
        val nextTablePaddr = Output(UInt(XLEN.W))
        val fault = Output(new MemoryFaultInfo(XLEN))
    })

    private val pageOffset = io.vaddr(11, 0)
    private val vpn0 = io.vaddr(20, 12)
    private val vpn1 = io.vaddr(29, 21)

    private val pteV = io.pte(0)
    private val pteR = io.pte(1)
    private val pteW = io.pte(2)
    private val pteX = io.pte(3)
    private val pteU = io.pte(4)
    private val pteA = io.pte(6)
    private val pteD = io.pte(7)
    private val ppn0 = io.pte(18, 10)
    private val ppn1 = io.pte(27, 19)
    private val ppn2 = io.pte(53, 28)

    private val canonical = io.vaddr(63, 39) === Fill(25, io.vaddr(38))
    private val reservedClear = io.pte(63, 54) === 0.U
    private val validEncoding = pteV && reservedClear && !(pteW && !pteR)
    private val isLeaf = validEncoding && (pteR || pteX)
    private val isPointer = validEncoding && !isLeaf

    private val level1Misaligned = io.level === 1.U && ppn0 =/= 0.U
    private val level2Misaligned = io.level === 2.U && (ppn1 =/= 0.U || ppn0 =/= 0.U)
    private val superpageMisaligned = level1Misaligned || level2Misaligned

    private val isStore = io.access === Sv39AccessType.Store
    private val isFetch = io.access === Sv39AccessType.Fetch

    private val accessAllowed = MuxLookup(io.access, false.B)(
        Seq(
            Sv39AccessType.Load  -> (pteR || (io.mxr && pteX)),
            Sv39AccessType.Store -> pteW,
            Sv39AccessType.Fetch -> pteX
        )
    )
    private val privilegeAllowed = Mux(
        io.priv === PrivilegeLevel.User,
        pteU,
        Mux(
            io.priv === PrivilegeLevel.Supervisor,
            Mux(pteU, io.sum && !isFetch, true.B),
            true.B
        )
    )
    private val accessedDirtyAllowed = pteA && (!isStore || pteD)
    private val terminalPointer = isPointer && io.level === 0.U
    private val leafFault = isLeaf && (superpageMisaligned || !accessAllowed || !privilegeAllowed || !accessedDirtyAllowed)
    private val pageFault = io.valid && (!canonical || !validEncoding || terminalPointer || leafFault)

    private val level0Paddr = Cat(0.U(8.W), ppn2, ppn1, ppn0, pageOffset)
    private val level1Paddr = Cat(0.U(8.W), ppn2, ppn1, vpn0, pageOffset)
    private val level2Paddr = Cat(0.U(8.W), ppn2, vpn1, vpn0, pageOffset)

    io.leaf := io.valid && isLeaf
    io.paddr := MuxLookup(io.level, level0Paddr)(
        Seq(
            0.U -> level0Paddr,
            1.U -> level1Paddr,
            2.U -> level2Paddr
        )
    )
    io.nextTablePaddr := Cat(0.U(8.W), io.pte(53, 10), 0.U(12.W))

    io.fault.valid := pageFault
    io.fault.cause := Mux(
        isFetch,
        MCause.InstrPageFault,
        Mux(isStore, MCause.StorePageFault, MCause.LoadPageFault)
    )
    io.fault.value := io.vaddr
}

class Sv39PageTableWalker(XLEN: Int = 64) extends Module {
    require(XLEN == 64, "Sv39PageTableWalker currently targets RV64 Sv39 only")

    val io = IO(new Bundle {
        val req = Flipped(Decoupled(new Sv39WalkReq(XLEN)))
        val resp = Decoupled(new Sv39WalkResp(XLEN))
        val mem = new Bundle {
            val req = Decoupled(new CacheReq(XLEN, XLEN))
            val resp = Flipped(Decoupled(new CacheResp(XLEN)))
        }
    })

    private val sIdle :: sReadReq :: sReadResp :: sDone :: Nil = Enum(4)
    private val state = RegInit(sIdle)
    private val reqReg = Reg(new Sv39WalkReq(XLEN))
    private val level = RegInit(2.U(2.W))
    private val tableBase = RegInit(0.U(XLEN.W))
    private val respReg = RegInit(0.U.asTypeOf(new Sv39WalkResp(XLEN)))

    private val vpn0 = reqReg.vaddr(20, 12)
    private val vpn1 = reqReg.vaddr(29, 21)
    private val vpn2 = reqReg.vaddr(38, 30)
    private val vpn = MuxLookup(level, vpn0)(
        Seq(
            0.U -> vpn0,
            1.U -> vpn1,
            2.U -> vpn2
        )
    )
    private val pteAddr = tableBase + (vpn << 3)

    private val translator = Module(new Sv39PteTranslator(XLEN))
    private val instantReadResp = state === sReadReq && io.mem.req.fire
    private val readRespActive = state === sReadResp || instantReadResp

    translator.io.valid := readRespActive && io.mem.resp.valid
    translator.io.vaddr := reqReg.vaddr
    translator.io.pte := io.mem.resp.bits.rdata
    translator.io.level := level
    translator.io.access := reqReg.access
    translator.io.priv := reqReg.priv
    translator.io.mxr := reqReg.mxr
    translator.io.sum := reqReg.sum

    io.req.ready := state === sIdle
    io.resp.valid := state === sDone
    io.resp.bits := respReg

    io.mem.req.valid := state === sReadReq
    io.mem.req.bits := 0.U.asTypeOf(io.mem.req.bits)
    io.mem.req.bits.addr := pteAddr
    io.mem.req.bits.vaddr := pteAddr
    io.mem.req.bits.cmd := CacheCmd.Read
    io.mem.req.bits.mask := "hff".U
    io.mem.req.bits.size := 3.U
    io.mem.req.bits.cacheable := true.B
    io.mem.req.bits.device := false.B

    io.mem.resp.ready := readRespActive

    when(io.req.fire) {
        reqReg := io.req.bits
        level := 2.U
        tableBase := Cat(0.U(8.W), io.req.bits.satp(43, 0), 0.U(12.W))
        respReg := 0.U.asTypeOf(respReg)
        state := sReadReq
    }

    when(state === sReadReq && io.mem.req.fire) {
        state := sReadResp
    }

    when(readRespActive && io.mem.resp.fire) {
        when(io.mem.resp.bits.err) {
            respReg.paddr := 0.U
            respReg.fault.valid := true.B
            respReg.fault.value := reqReg.vaddr
            respReg.fault.cause := Mux(
                reqReg.access === Sv39AccessType.Fetch,
                MCause.InstrAccessFault,
                Mux(reqReg.access === Sv39AccessType.Store, MCause.StoreAccessFault, MCause.LoadAccessFault)
            )
            state := sDone
        }.elsewhen(translator.io.fault.valid) {
            respReg.paddr := 0.U
            respReg.fault := translator.io.fault
            state := sDone
        }.elsewhen(translator.io.leaf) {
            respReg.paddr := translator.io.paddr
            respReg.fault.valid := false.B
            respReg.fault.cause := 0.U
            respReg.fault.value := 0.U
            state := sDone
        }.otherwise {
            tableBase := translator.io.nextTablePaddr
            level := level - 1.U
            state := sReadReq
        }
    }

    when(io.resp.fire) {
        state := sIdle
    }
}
