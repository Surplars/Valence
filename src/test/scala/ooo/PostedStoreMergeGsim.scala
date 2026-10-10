package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Standalone environmental component premises only. This does not execute a CPU,
  * a cache SRAM, the acquire engine, a coherence home, or a real TileLink bus.
  */
class PostedStoreMergeGsim(generationBits: Int = 64) extends Module {
    private val c = PostedStoreMergeConfig(enabled = true, generationBits = generationBits,
        cacheSets = 8, guaranteedBase = 4096, guaranteedBytes = 4096)
    c.requireCacheAperture(4096, 4096)
    val io = IO(new Bundle {
        val enq = Flipped(Irrevocable(new PostedStoreOffer(c)))
        val cacheAdmission = Input(new PostedStoreAdmission(c))
        val contextEpoch = Input(UInt(c.epochBits.W))
        val seal = Input(Bool())
        val endEpisode = Input(Bool())
        val acknowledged = Input(Valid(new PostedStoreMember(c)))
        // One authored captured cache event per cycle, with explicit full lineage.
        val event = Input(new PostedLineEvent(c))
        val acquireValid = Input(Bool())
        val refillValid = Input(Bool())
        val refillError = Input(Bool())
        val refillToT = Input(Bool())
        val refillHasData = Input(Bool())
        val refillGrantAcked = Input(Bool())
        val refillWord0 = Input(UInt(64.W))
        val refillWord1 = Input(UInt(64.W))
        val refillWord2 = Input(UInt(64.W))
        val refillWord3 = Input(UInt(64.W))
        val refillWord4 = Input(UInt(64.W))
        val refillWord5 = Input(UInt(64.W))
        val refillWord6 = Input(UInt(64.W))
        val refillWord7 = Input(UInt(64.W))
        val writebackTicket = Input(new PostedWritebackTicket(c))
        val writebackAttach = Input(Bool())
        val writebackSent = Input(Bool())
        val writebackComplete = Input(Bool())
        val victimCancel = Input(Bool())
        val installReady = Input(Bool())
        val drainReady = Input(Bool())
        val releaseReady = Input(Bool())
        val fallbackReady = Input(Bool())
        val fallbackAcknowledged = Input(Valid(new PostedFallbackAcknowledgement(c)))
        val eligible = Output(Bool())
        val canJoin = Output(Bool())
        val admission = Output(new PostedLineContext(c))
        val accepted = Output(Valid(new PostedStoreAcceptance(c)))
        val refillReady = Output(Bool())
        val installValid = Output(Bool())
        val installEvent = Output(new PostedLineEvent(c))
        val installWord0 = Output(UInt(64.W))
        val installWord1 = Output(UInt(64.W))
        val installWord2 = Output(UInt(64.W))
        val installWord3 = Output(UInt(64.W))
        val installWord4 = Output(UInt(64.W))
        val installWord5 = Output(UInt(64.W))
        val installWord6 = Output(UInt(64.W))
        val installWord7 = Output(UInt(64.W))
        val drained = Output(Valid(new PostedStoreMember(c)))
        val released = Output(Valid(new PostedLineEvent(c)))
        val fallback = Output(Valid(new PostedStoreOffer(c)))
        val busy = Output(Bool())
        val exhausted = Output(Bool())
        val failed = Output(Bool())
        val stores = Output(UInt(c.countBits.W))
        val lines = Output(UInt(2.W))
        val episodeActive = Output(Bool())
    })
    val owner = Module(new PostedStoreMerge(c))
    owner.io.enq <> io.enq
    owner.io.cacheAdmission := io.cacheAdmission
    owner.io.contextEpoch := io.contextEpoch
    owner.io.seal := io.seal
    owner.io.endEpisode := io.endEpisode
    owner.io.acknowledged := io.acknowledged
    owner.io.acquireIssued.valid := io.acquireValid
    owner.io.acquireIssued.bits := io.event
    owner.io.refill.valid := io.refillValid
    owner.io.refill.bits.context := io.event.context
    owner.io.refill.bits.reservation := io.event.reservation
    owner.io.refill.bits.data := Cat(io.refillWord7, io.refillWord6, io.refillWord5, io.refillWord4,
        io.refillWord3, io.refillWord2, io.refillWord1, io.refillWord0)
    owner.io.refill.bits.error := io.refillError
    owner.io.refill.bits.toT := io.refillToT
    owner.io.refill.bits.hasData := io.refillHasData
    owner.io.refill.bits.grantAcked := io.refillGrantAcked
    val wbPorts = Seq(owner.io.writebackAttached, owner.io.writebackSent, owner.io.writebackCompleted)
    val wbValid = Seq(io.writebackAttach, io.writebackSent, io.writebackComplete)
    for ((port, valid) <- wbPorts.zip(wbValid)) {
        port.valid := valid
        port.bits.context := io.event.context
        port.bits.reservation := io.event.reservation
        port.bits.ticket := io.writebackTicket
    }
    owner.io.victimCancelled.valid := io.victimCancel
    owner.io.victimCancelled.bits := io.event
    owner.io.install.ready := io.installReady
    owner.io.drained.ready := io.drainReady
    owner.io.released.ready := io.releaseReady
    owner.io.fallback.ready := io.fallbackReady
    owner.io.fallbackAcknowledged := io.fallbackAcknowledged
    io.eligible := owner.io.eligible
    io.canJoin := owner.io.canJoin
    io.admission := owner.io.admission
    io.accepted := owner.io.accepted
    io.refillReady := owner.io.refill.ready
    io.installValid := owner.io.install.valid
    io.installEvent.context := owner.io.install.bits.context
    io.installEvent.reservation := owner.io.install.bits.reservation
    val words = Seq(io.installWord0, io.installWord1, io.installWord2, io.installWord3,
        io.installWord4, io.installWord5, io.installWord6, io.installWord7)
    for ((word, index) <- words.zipWithIndex) { word := owner.io.install.bits.data(64 * index + 63, 64 * index) }
    io.drained.valid := owner.io.drained.valid
    io.drained.bits := owner.io.drained.bits
    io.released.valid := owner.io.released.valid
    io.released.bits := owner.io.released.bits
    io.fallback.valid := owner.io.fallback.valid
    io.fallback.bits := owner.io.fallback.bits
    io.busy := owner.io.busy
    io.exhausted := owner.io.exhausted
    io.failed := owner.io.failed
    io.stores := owner.io.stores
    io.lines := owner.io.lines
    io.episodeActive := owner.io.episodeActive
}

object PostedStoreMergeGsimMain extends App {
    require(args.length == 2 && Set(2, 64).contains(args(1).toInt), "target directory and explicit generation 2/64 required")
    ChiselStage.emitCHIRRTLFile(new PostedStoreMergeGsim(args(1).toInt), Array("--target-dir", args(0)))
}
