package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._
import soc.platform.CommonA1RebuildProfile

/** Real M3 LSU, without a backend or a synthetic successful-store state.
  * Every source must cross its actual request and reply ports. The host supplies
  * a checked certificate as an explicit boundary premise, not a translation test.
  * Forwarded bytes come from the real completed StoreForward payload; the host
  * derives expected load bytes independently from the accepted source store.
  */
class CompletedCanonicalForwardGsim(entries: Int = 4) extends Module {
    val p = CommonA1RebuildProfile.FullR1M3.config.coreParams.copy(memoryEntries = entries)
    require(Set(2, 4).contains(entries))
    require(p.completedCanonicalStoreForwarding && p.completionTopology == "dual-owner" &&
        p.canonicalVirtualStoreOverlap && p.virtualRamLoadPrecheck && p.tagBits == 64 &&
        p.dataReturnHandleBits == 0 && !p.frozenStoreProofEnabled)
    val io = IO(new Bundle {
        // Scalar host inputs intentionally avoid generated Vec accessors.
        val startValid = Input(Bool())
        val startReady = Output(Bool())
        val tokenIndex = Input(UInt(p.robBits.W))
        val tokenTag = Input(UInt(p.tagBits.W))
        val pc = Input(UInt(64.W))
        val address = Input(UInt(64.W))
        val physicalAddress = Input(UInt(64.W))
        val data = Input(UInt(64.W))
        val size = Input(UInt(2.W))
        val unsignedLoad = Input(Bool())
        val store = Input(Bool())
        val virtualized = Input(Bool())
        val prechecked = Input(Bool())
        val forwarded = Input(Bool())
        val parallel = Input(Bool())
        val epoch = Input(UInt(32.W))
        val originValid = Input(Bool())
        val certificateValid = Input(Bool())
        val sourceIndex = Input(UInt(p.robBits.W))
        val sourceTag = Input(UInt(p.tagBits.W))
        val sourceEpoch = Input(UInt(32.W))
        val sourceVirtualAddress = Input(UInt(64.W))
        val sourcePhysicalAddress = Input(UInt(64.W))
        val sourceSize = Input(UInt(3.W))
        val sourceMask = Input(UInt(8.W))
        val forwardDataXor = Input(UInt(64.W))
        val relaxValid = Input(Bool())
        val cancelValid = Input(Bool())
        val cancelIndex = Input(UInt(p.robBits.W))
        val cancelTag = Input(UInt(p.tagBits.W))
        val memory = new DataPort
        val complete = Decoupled(new BackendCompletion(p))
        val source = Output(Valid(new StoreForward(p)))
        val origin = Output(Valid(new CanonicalStoreOrigin(p)))
        val requestOwner = Output(Valid(new RobToken(p)))
        val live = Output(UInt(entries.W))
        val phase = Output(UInt((2 * entries).W))
        val slotStart = Output(UInt(entries.W))
        val slotComplete = Output(UInt(entries.W))
        val slotResponse = Output(UInt(entries.W))
        val busy = Output(Bool())
        val discarded = Output(Bool())
        val acceptedForward = Output(Bool())
        val configuredSlots = Output(UInt(3.W))
    })
    val lsu = Module(new ParallelLoadStoreUnit(p, canonicalHandoff = true))
    lsu.io.start.valid := io.startValid
    lsu.io.start.bits := 0.U.asTypeOf(new MemoryOperation(p))
    val start = lsu.io.start.bits
    start.token.index := io.tokenIndex
    start.token.tag := io.tokenTag
    start.pc := io.pc
    start.address := io.address
    start.physicalAddress := io.physicalAddress
    start.data := io.data
    start.size := io.size
    start.unsigned := io.unsignedLoad
    start.store := io.store
    start.virtualized := io.virtualized
    start.precheckedLoad := io.prechecked
    start.translationEpoch := io.epoch
    start.canonicalStoreEpoch.get.valid := io.originValid
    start.canonicalStoreEpoch.get.bits := io.epoch
    start.forward.valid := io.forwarded
    start.forward.bits := lsu.io.forwardStore.bits.data ^ io.forwardDataXor
    val certificate = start.canonicalForward.get
    certificate.valid := io.certificateValid
    certificate.bits.origin.token.index := io.sourceIndex
    certificate.bits.origin.token.tag := io.sourceTag
    certificate.bits.origin.epoch := io.sourceEpoch
    certificate.bits.virtualAddress := io.sourceVirtualAddress
    certificate.bits.physicalAddress := io.sourcePhysicalAddress
    certificate.bits.size := io.sourceSize
    certificate.bits.mask := io.sourceMask
    lsu.io.parallel := io.parallel
    lsu.io.relaxStoreOwner.get.valid := io.relaxValid
    lsu.io.relaxStoreOwner.get.bits := certificate.bits.origin.token
    lsu.io.issueDestination.foreach(_ := 0.U.asTypeOf(Valid(UInt(p.physBits.W))))
    lsu.io.boundHeadStoreOverlapQualified.foreach(_ := false.B)
    lsu.io.fastStoreRetire := false.B
    lsu.io.fastLoadRetire := false.B
    for (i <- 0 until entries) {
        lsu.io.cancel(i) := io.cancelValid && lsu.io.live(i) &&
            lsu.io.owner(i).index === io.cancelIndex && lsu.io.owner(i).tag === io.cancelTag
    }
    io.startReady := lsu.io.start.ready
    io.memory <> lsu.io.memory
    io.complete <> lsu.io.complete
    io.source := lsu.io.forwardStore
    io.origin := lsu.io.canonicalStoreOrigin.get
    io.requestOwner := lsu.io.requestOwner
    io.live := lsu.io.live.asUInt
    io.phase := lsu.io.phase.asUInt
    // Observation only. No test signal changes a slot's state, credit or handshake.
    io.slotStart := VecInit(lsu.slots.map(s =>
        BoringUtils.bore(s.io.start.valid) && BoringUtils.bore(s.io.start.ready))).asUInt
    io.slotComplete := VecInit(lsu.slots.map(s =>
        BoringUtils.bore(s.io.complete.valid) && BoringUtils.bore(s.io.complete.ready))).asUInt
    io.slotResponse := VecInit(lsu.slots.map(s =>
        BoringUtils.bore(s.io.memory.response.valid) && BoringUtils.bore(s.io.memory.response.ready))).asUInt
    io.busy := lsu.io.busy
    io.discarded := lsu.io.discarded
    io.acceptedForward := lsu.io.forwarded
    io.configuredSlots := entries.U
}

object CompletedCanonicalForwardGsimMain extends App {
    require(args.length == 1 || args.length == 2, "output-directory [2|4]")
    ChiselStage.emitCHIRRTLFile(new CompletedCanonicalForwardGsim(args.lift(1).map(_.toInt).getOrElse(4)),
        Array("--target-dir", args(0)))
}
