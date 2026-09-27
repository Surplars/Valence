package soc.ip.interrupt

import chisel3._
import chisel3.util._
import soc.ip.bus._

case class ImsicParams(
    identities: Int = 127,
    guestFiles: Int = 0,
    machineBase: BigInt = BigInt("24000000", 16),
    supervisorBase: BigInt = BigInt("28000000", 16)
) {
    require(identities >= 63 && identities <= 2047 && (identities + 1) % 64 == 0)
    require(guestFiles >= 0 && guestFiles <= 63)
    val files           = 2 + guestFiles
    val groups          = (identities + 1) / 64
    val supervisorPages = 1 << log2Ceil(guestFiles + 1)
    val supervisorBytes = BigInt(supervisorPages) * 4096
    require(machineBase >= 0 && machineBase % 4096 == 0 && machineBase + 4096 <= (BigInt(1) << 64))
    require(
        supervisorBase >= 0 && supervisorBase % supervisorBytes == 0 &&
            supervisorBase + supervisorBytes <= (BigInt(1) << 64)
    )
    require(machineBase + 4096 <= supervisorBase || supervisorBase + supervisorBytes <= machineBase)
}

/** File index 0=M, 1=S, 2=guest1, etc. Caller has already checked privilege/VGEIN and commit authority. */
class ImsicCsrRequest extends Bundle {
    val file      = UInt(8.W)
    val selector  = UInt(12.W)
    val topei     = Bool()
    val operation = UInt(2.W) // 0 read, 1 write, 2 set, 3 clear; write suppression is the caller's duty
    val data      = UInt(64.W)
}

/** Reusable RV64 AIA 1.0 IMSIC. No CPU/ROB/global-config dependency. See docs/modular-soc.md. */
class Imsic(val p: ImsicParams = ImsicParams()) extends Module {
    val io = IO(new Bundle {
        val mmio        = Flipped(new RegisterPort)
        val csrRequest  = Flipped(Decoupled(new ImsicCsrRequest))
        val csrResponse = Decoupled(new RegisterResponse)
        val interrupts  = Output(UInt(p.files.W))
    })
    val pending   = RegInit(VecInit(Seq.fill(p.files)(VecInit(Seq.fill(p.groups)(0.U(64.W))))))
    val enabled   = RegInit(VecInit(Seq.fill(p.files)(VecInit(Seq.fill(p.groups)(0.U(64.W))))))
    val delivery  = RegInit(VecInit(Seq.fill(p.files)(false.B)))
    val threshold = RegInit(VecInit(Seq.fill(p.files)(0.U(11.W))))
    val top       = Wire(Vec(p.files, UInt(11.W)))
    for (f <- 0 until p.files) {
        val candidates = (0 until p.groups).map { g =>
            val active = pending(f)(g) & enabled(f)(g)
            val local  = PriorityEncoder(active)
            (active.orR, (g * 64).U(11.W) + local)
        }
        val any   = candidates.map(_._1).reduce(_ || _)
        val first = PriorityMux(candidates)
        top(f) := Mux(any && (threshold(f) === 0.U || first < threshold(f)), first, 0.U)
    }
    io.interrupts := VecInit((0 until p.files).map(f => delivery(f) && top(f) =/= 0.U)).asUInt
    // Registered response storage decouples ready in each direction, with independent credits per port.
    val mmioResponses = Module(new Queue(new RegisterResponse, 2, pipe = false, flow = false))
    val csrResponses  = Module(new Queue(new RegisterResponse, 2, pipe = false, flow = false))
    io.mmio.response <> mmioResponses.io.deq
    io.csrResponse <> csrResponses.io.deq
    io.mmio.request.ready      := mmioResponses.io.enq.ready
    io.csrRequest.ready        := csrResponses.io.enq.ready
    mmioResponses.io.enq.valid := io.mmio.request.valid
    csrResponses.io.enq.valid  := io.csrRequest.valid

    val bus        = io.mmio.request.bits
    val machine    = bus.address >= p.machineBase.U && bus.address < (p.machineBase + 4096).U(65.W)
    val supervisor = bus.address >= p.supervisorBase.U && bus.address < (p.supervisorBase + p.supervisorBytes).U(65.W)
    val supervisorPage  = (bus.address - p.supervisorBase.U) >> 12
    val fileIndex       = Mux(machine, 0.U, supervisorPage + 1.U)
    val implementedPage = machine || (supervisor && supervisorPage <= p.guestFiles.U)
    val busError        = !(machine || supervisor) || bus.size =/= 2.U || bus.address(1, 0) =/= 0.U ||
        (bus.write && bus.byteEnable =/= "h0f".U)
    val bigEndian = bus.address(11, 0) === 4.U
    val msiData   = Mux(bigEndian, Cat((0 until 4).map(i => bus.data(i * 8 + 7, i * 8))), bus.data(31, 0))
    val msi       = io.mmio.request.fire && !busError && implementedPage && bus.write &&
        (bus.address(11, 0) === 0.U || bigEndian) && msiData =/= 0.U && msiData <= p.identities.U
    mmioResponses.io.enq.bits.data  := 0.U
    mmioResponses.io.enq.bits.error := busError

    val csr          = io.csrRequest.bits
    val inRange      = csr.selector >= "h70".U && csr.selector <= "hff".U
    val bitmap       = csr.selector >= "h80".U
    val csrError     = csr.file >= p.files.U || (!csr.topei && (!inRange || (bitmap && csr.selector(0))))
    val csrReadValue = WireDefault(0.U(64.W))
    for (f <- 0 until p.files) {
        when(csr.file === f.U) {
            when(csr.topei) { csrReadValue := (top(f) << 16) | top(f) }
                .elsewhen(csr.selector === "h70".U) { csrReadValue := delivery(f) }
                .elsewhen(csr.selector === "h72".U) { csrReadValue := threshold(f) }
            for (g <- 0 until p.groups) {
                when(!csr.topei && csr.selector === (0x80 + 2 * g).U) { csrReadValue := pending(f)(g) }
                when(!csr.topei && csr.selector === (0xc0 + 2 * g).U) { csrReadValue := enabled(f)(g) }
            }
        }
    }
    csrResponses.io.enq.bits.data  := Mux(csrError, 0.U, csrReadValue)
    csrResponses.io.enq.bits.error := csrError
    val updated = MuxLookup(csr.operation, csrReadValue)(
        Seq(1.U -> csr.data, 2.U -> (csrReadValue | csr.data), 3.U -> (csrReadValue & ~csr.data))
    )
    val csrWrite = io.csrRequest.fire && !csrError && csr.operation =/= 0.U
    for (f <- 0 until p.files) {
        val writing = csrWrite && csr.file === f.U
        when(writing && !csr.topei && csr.selector === "h70".U) { delivery(f) := updated(0) }
        when(writing && !csr.topei && csr.selector === "h72".U && updated <= p.identities.U) {
            threshold(f) := updated(10, 0)
        }
        for (g <- 0 until p.groups) {
            val validMask    = (if (g == 0) (BigInt(1) << 64) - 2 else (BigInt(1) << 64) - 1).U(64.W)
            val pendingWrite = writing && !csr.topei && csr.selector === (0x80 + 2 * g).U
            val claim        = writing && csr.topei && top(f) =/= 0.U && top(f)(10, 6) === g.U
            val claimMask    = Mux(claim, UIntToOH(top(f)(5, 0), 64), 0.U(64.W))
            val incoming     = msi && fileIndex === f.U && msiData(10, 6) === g.U
            val incomingMask = Mux(incoming, UIntToOH(msiData(5, 0), 64), 0.U(64.W))
            // CSR operation precedes concurrent MSI: a claim cannot erase a newly arriving interrupt.
            pending(f)(g) := ((Mux(pendingWrite, updated, pending(f)(g)) & ~claimMask) | incomingMask) & validMask
            when(writing && !csr.topei && csr.selector === (0xc0 + 2 * g).U) {
                enabled(f)(g) := updated & validMask
            }
        }
    }
}
