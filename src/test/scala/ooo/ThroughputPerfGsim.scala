package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

/** The board's exact backend geometry and timing switches, with the existing bare
  * core instruction/RAM devices. Compressed fetch/cache behavior is deliberately
  * covered by the separate exact-board smoke, not claimed by this wrapper.
  */
object ThroughputPerfConfig {
    def params(profile: String): OooParams = {
        require(Set("staged-control-heads", "staged-throughput", "staged-gmac-ready", "staged-ethernet",
            "staged-fetch-feedback").contains(profile))
        BoardSocConfig.timingParams(profile).copy(
            speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 4096,
            compressedInstructions = false, parallelFetchAlignment = false, parallelFetchTagLookup = false,
            alignedFetchPmp = false, rawFetchPresence = false, parallelReturnStackControl = false,
            parallelPacketPmp = false, wordSpanPacketPmp = false, balancedPacketPmp = false,
            capturedFetchPermission = false, registeredFetchWindow = false)
    }
}

class ThroughputPerfGsim(p: OooParams) extends IntegerCoreGsim(p) {
    override def desiredName: String = "IntegerCoreGsim"
    // GSIM applies registered state at the beginning of step(). The external
    // instruction device needs the next raw cursor before supplying that step.
    // This is device stimulus, never the expected architectural retirement PC.
    val nextFetchPc = IO(Output(UInt(64.W)))
    nextFetchPc := core.io.nextFetchPc.getOrElse(core.io.fetchPc)
    // Test-only coverage taps: the production SoC interface stays unchanged.
    // Read actual grants/owners rather than inferring execution-slot coverage
    // from a coincidentally correct architectural result.
    val slot0HoldAndLane1Progress = IO(Output(Bool()))
    val olderLane0BranchResolution = IO(Output(Bool()))
    val aluForwardingHit = IO(Output(Bool()))
    if (p.registeredIssueExecute) {
        val backend = core.backend
        val valid0 = BoringUtils.bore(backend.executionStages(0).io.deq.valid)
        val ready0 = BoringUtils.bore(backend.executionStages(0).io.deq.ready)
        val valid1 = BoringUtils.bore(backend.executionStages(1).io.deq.valid)
        val ready1 = BoringUtils.bore(backend.executionStages(1).io.deq.ready)
        slot0HoldAndLane1Progress := valid0 && !ready0 && valid1 && ready1

        val resolves0 = BoringUtils.bore(backend.newResolutions(0).valid)
        val resolves1 = BoringUtils.bore(backend.newResolutions(1).valid)
        val owner0 = BoringUtils.bore(backend.selected(0).bits)
        val owner1 = BoringUtils.bore(backend.selected(1).bits)
        val head = BoringUtils.bore(backend.head)
        // These owners may have entered on DIFFERENT cycles. Modulo ROB age,
        // not execution lane number, decides the older simultaneous redirect.
        olderLane0BranchResolution := resolves0 && resolves1 && (owner0 - head) < (owner1 - head)

        // Tap queued source IDs directly: the board currently uses binary PRF
        // operand selection, so the optional one-hot helper is not instantiated.
        // Individual leaf taps keep this independent of either read topology.
        val sources1 = VecInit((0 until p.robEntries).map(i =>
            BoringUtils.bore(backend.queue(i).renamed.source1)))
        val sources2 = VecInit((0 until p.robEntries).map(i =>
            BoringUtils.bore(backend.queue(i).renamed.source2)))
        val enqueued = BoringUtils.bore(backend.executionEnqueued)
        val dispatched = BoringUtils.bore(backend.dispatched)
        val wakes = BoringUtils.bore(backend.executionWake)
        // Decoded unused sources are physical x0, while a valid ALU promise
        // always writes a nonzero physical destination. Count only a new slot
        // that actually captures the promised source, never a blocked offer.
        aluForwardingHit := (0 until p.completionWidth).map { lane =>
            enqueued(lane) && wakes.map(wake => wake.valid &&
                (wake.bits === sources1(dispatched(lane).bits) ||
                    wake.bits === sources2(dispatched(lane).bits))).reduce(_ || _)
        }.reduce(_ || _)
    } else {
        slot0HoldAndLane1Progress := false.B
        olderLane0BranchResolution := false.B
        aluForwardingHit := false.B
    }
}

object ThroughputPerfGsimMain extends App {
    val profile = args.lift(1).getOrElse("staged-throughput")
    ChiselStage.emitCHIRRTLFile(new ThroughputPerfGsim(ThroughputPerfConfig.params(profile)),
        Array("--target-dir", args.head))
}
