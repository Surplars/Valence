package soc.platform

import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Opt-in conservative H integration, not a replacement for either throughput profile.
  * Scalar lane 0 carries physical data; lane 1 carries independent fetch/I-PTE/D-PTE
  * owners. Each read source has one slot, round-robin admission and a retained reply.
  * The registered offer queue preserves native payload stability under backpressure.
  * No cache, TLB, host alias or synthetic memory lives here. Cold reset must cover
  * tile and fabric together; runtime parking and unilateral warm reset are unsupported.
  */
class CommonHypervisorCpuTile(
    ramBytes: BigInt,
    romBytes: Int,
    mmioRegions: Seq[CommonAddressRegion],
    boundary: CommonCpuTilePortParams = CommonCpuTilePortParams(),
    guestFiles: Int = 3,
    atomicMemory: Boolean = false
) extends Module {
    require(ramBytes > 0 && romBytes > 0 && guestFiles == 3)
    require(CommonPlatformAbi.romBase + romBytes <= CommonPlatformAbi.ramBase)
    require(CommonPlatformAbi.ramBase + ramBytes <= (BigInt(1) << 64))
    require(!boundary.runtimeMaintenance && !boundary.runtimeCancellation && !boundary.runtimeInterruptHold,
        "H platform profile supports cold start only, not runtime parking")
    val core = Module(new HypervisorMachineCore(platformIntegration = true,
        atomicMemory = atomicMemory, ramBase = if (atomicMemory) CommonPlatformAbi.ramBase else BigInt(0),
        ramBytes = if (atomicMemory) ramBytes else BigInt(0)))
    val io = IO(new Bundle {
        val bus = new CommonCpuTilePort(boundary)
        val enable = Input(Bool())
        val commitEnable = Input(Bool())
        val commit0 = Output(Valid(new CommitRecord(core.p)))
        val commit1 = Output(Valid(new CommitRecord(core.p)))
        val trap = Output(Valid(new HeadException(core.p)))
        val fetchPc = Output(UInt(64.W))
        val virtualized = Output(Bool())
    })
    // Initial boot hold is supported. Once enabled, enable may not park a live core:
    // doing so would suppress retirement rather than quiesce accepted owners.
    val started = RegInit(false.B)
    when(io.enable) { started := true.B }
    assert(!started || io.enable, "H tile enable is a cold-start gate, not runtime hold")
    core.io.enable := io.enable
    core.io.commitEnable := io.commitEnable
    core.io.msi <> io.bus.msi
    core.io.timerInterrupt := io.bus.timerInterrupt
    core.io.timeValue := io.bus.timeSnapshot
    assert(!io.bus.softwareInterrupt, "ABI 1 has no machine software interrupt source")
    io.commit0 := core.io.commit0
    io.commit1 := core.io.commit1
    io.trap := core.io.trap
    io.fetchPc := core.io.fetchPc
    io.virtualized := core.io.virtualized

    // Check the complete byte interval using 65-bit arithmetic, including wraparound.
    def inRegion(address: UInt, size: UInt, base: BigInt, bytes: BigInt): Bool = {
        val end = address +& (1.U(65.W) << size)
        address >= base.U(65.W) && end <= (base + bytes).U(65.W)
    }
    def inRam(address: UInt, size: UInt): Bool =
        inRegion(address, size, CommonPlatformAbi.ramBase, ramBytes)
    def inRom(address: UInt, size: UInt): Bool =
        inRegion(address, size, CommonPlatformAbi.romBase, romBytes)
    def inMemory(address: UInt, size: UInt): Bool = inRam(address, size) || inRom(address, size)
    val fc = core.io.fetchPhysicalCheck.bits
    core.io.fetchPmaDenied := !inMemory(fc.address, fc.size)
    val dc = core.io.dataPhysicalCheck.bits
    val dataMmio = mmioRegions.map(r => inRegion(dc.address, dc.size, r.base, r.bytes))
        .foldLeft(false.B)(_ || _)
    val dataAllowed = inRam(dc.address, dc.size) ||
        (inRom(dc.address, dc.size) && dc.access === PmpAccess.read) || (dataMmio && !dc.forceExecute)
    // Permission (including LR read vs SC write) is separate from atomic PMA.
    // ROM and MMIO never accept atomics, regardless of decoder capabilities.
    val atomicAllowed = atomicMemory.B && inRam(dc.address, dc.size)
    core.io.dataPmaDenied := !dataAllowed || (dc.atomic && !atomicAllowed)
    core.io.dataPmaUncached := dataMmio

    val dataOwner = Module(new CommonNativeOwnerAdapter(boundary, carriesClear = true))
    dataOwner.io.native <> core.io.data
    dataOwner.io.needsCoherenceLookup := true.B
    dataOwner.io.clearReservation := core.io.trap.valid
    io.bus.scalar(0) <> dataOwner.io.transport

    val readOwner = Module(new CommonNativeOwnerAdapter(boundary, carriesClear = false))
    readOwner.io.needsCoherenceLookup := true.B
    readOwner.io.clearReservation := false.B
    io.bus.scalar(1) <> readOwner.io.transport
    val idle :: offer :: awaiting :: reply :: Nil = Enum(4)
    val states = RegInit(VecInit(Seq.fill(3)(idle)))
    val addresses = Reg(Vec(3, UInt(64.W)))
    val replies = Reg(Vec(3, UInt(64.W)))
    val errors = Reg(Vec(3, Bool()))
    val requests = Seq(core.io.instruction.request, core.io.fetchPte.request, core.io.dataPte.request)
    val replyReady = Seq(core.io.instruction.response.ready, core.io.fetchPte.response.ready,
        core.io.dataPte.response.ready)
    for (i <- 0 until 3) {
        requests(i).ready := states(i) === idle
        val size = (if (i == 0) 1 else 3).U(2.W)
        val aligned = if (i == 0) !requests(i).bits(0) else requests(i).bits(2, 0) === 0.U
        val permitted = aligned && inMemory(requests(i).bits, size)
        when(requests(i).fire) {
            addresses(i) := requests(i).bits
            errors(i) := !permitted
            replies(i) := 0.U
            states(i) := Mux(permitted, offer, reply)
        }
        when(states(i) === reply && replyReady(i)) { states(i) := idle }
    }
    // Fetch parcels are selected from the physical native beat, not an assumed
    // right-justified response. PTE requests are naturally aligned eight-byte reads.
    core.io.instruction.response.valid := states(0) === reply
    core.io.instruction.response.bits := (replies(0) >> Cat(addresses(0)(2, 1), 0.U(4.W)))(15, 0)
    core.io.instruction.responseError := errors(0)
    core.io.instruction.responsePageFault := false.B
    for ((port, i) <- Seq(core.io.fetchPte -> 1, core.io.dataPte -> 2)) {
        port.response.valid := states(i) === reply
        port.response.bits.data := replies(i)
        port.response.bits.error := errors(i)
    }
    class ReadOffer extends Bundle {
        val source = UInt(2.W)
        val address = UInt(64.W)
    }
    val arbiter = Module(new RRArbiter(new ReadOffer, 3))
    val offers = Module(new Queue(new ReadOffer, 3, pipe = false, flow = false))
    val owners = Module(new Queue(UInt(2.W), 3, pipe = false, flow = false))
    for (i <- 0 until 3) {
        arbiter.io.in(i).valid := states(i) === offer
        arbiter.io.in(i).bits.source := i.U
        arbiter.io.in(i).bits.address := addresses(i)
        when(arbiter.io.in(i).fire) { states(i) := awaiting }
    }
    offers.io.enq <> arbiter.io.out
    val physical = readOwner.io.native
    physical.request.valid := offers.io.deq.valid && owners.io.enq.ready
    physical.request.bits := 0.U.asTypeOf(physical.request.bits)
    physical.request.bits.address := offers.io.deq.bits.address
    physical.request.bits.size := Mux(offers.io.deq.bits.source === 0.U, 1.U, 3.U)
    physical.request.bits.mask := Mux(offers.io.deq.bits.source === 0.U,
        (3.U(8.W) << offers.io.deq.bits.address(2, 0))(7, 0), "hff".U)
    offers.io.deq.ready := physical.request.ready && owners.io.enq.ready
    owners.io.enq.valid := physical.request.fire
    owners.io.enq.bits := offers.io.deq.bits.source
    physical.response.ready := owners.io.deq.valid
    owners.io.deq.ready := physical.response.fire
    when(physical.response.fire) {
        val source = owners.io.deq.bits
        assert(states(source) === awaiting, "physical read reply lost its independent source owner")
        replies(source) := physical.response.bits.data
        errors(source) := physical.response.bits.error || physical.response.bits.pageFault
        states(source) := reply
    }

    // This profile owns no TL cache clients. Unexpected traffic is a wiring error.
    for (port <- Seq(io.bus.instructionFetch) ++ io.bus.coherent.toSeq) {
        port.a.valid := false.B; port.a.bits := 0.U.asTypeOf(port.a.bits)
        port.c.valid := false.B; port.c.bits := 0.U.asTypeOf(port.c.bits)
        port.e.valid := false.B; port.e.bits := 0.U.asTypeOf(port.e.bits)
        port.b.ready := false.B; port.d.ready := false.B
        assert(!port.b.valid && !port.d.valid, "fabric addressed an inactive H tile TL client")
    }
    for (grant <- io.bus.lineGrant) {
        grant.ready := false.B
        assert(!grant.valid, "fabric addressed an inactive H tile line-grant client")
    }

    // FENCE.I must wait for both real private owners and the matching shared
    // fabric epoch. No private dirty cache exists, but physical responses still do.
    val fence = core.io.platformFence.get
    val epoch = RegInit(0.U(boundary.maintenanceEpochBits.W))
    val fenceSeen = RegInit(false.B)
    val requestSent = RegInit(false.B)
    val fabricDone = RegInit(false.B)
    when(fence && !fenceSeen) { epoch := epoch + 1.U; fenceSeen := true.B }
    when(!fence) { fenceSeen := false.B; requestSent := false.B; fabricDone := false.B }
    val readsIdle = states.map(_ === idle).reduce(_ && _) && offers.io.count === 0.U && owners.io.count === 0.U
    val privateIdle = core.io.privateOwnersIdle.get && dataOwner.io.idle && readOwner.io.idle && readsIdle
    io.bus.maintenance.ready := false.B
    io.bus.maintenanceStatus.valid := fence && fenceSeen && privateIdle && !requestSent
    io.bus.maintenanceStatus.bits.epoch := epoch
    io.bus.maintenanceStatus.bits.privateOwnersDrained := privateIdle
    io.bus.maintenanceStatus.bits.dirtyWritebackCompleted := true.B
    io.bus.maintenanceStatus.bits.fetchQuiescent := privateIdle
    io.bus.maintenanceStatus.bits.invalidationsCompleted := false.B
    when(io.bus.maintenanceStatus.fire) { requestSent := true.B }
    io.bus.fabricDrainedEpoch.ready := requestSent && !fabricDone
    when(io.bus.fabricDrainedEpoch.fire) {
        assert(fence && io.bus.fabricDrainedEpoch.bits === epoch, "H tile accepted a stale fabric epoch")
        fabricDone := true.B
    }
    core.io.platformFenceReady.get := fabricDone && privateIdle
}
