package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util.Valid
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

/** The board's exact backend geometry and timing switches, with the existing bare
  * core instruction/RAM devices. Compressed fetch/cache behavior is deliberately
  * covered by the separate exact-board smoke, not claimed by this wrapper.
  */
object ThroughputPerfConfig {
    def params(profile: String): OooParams = {
        require(Set("staged-control-heads", "staged-throughput", "staged-gmac-ready", "staged-ethernet",
            "staged-fetch-feedback", "staged-load-issue", "staged-fetch-turnover",
            BoardSocConfig.memoryCapacityProfile).contains(profile))
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
    // Passive, full-token event timestamps for the short CPU latency matrix.
    // The request/response device stays outside the CPU; these are not SoC TLB/cache latencies.
    val loadStart = IO(Output(Valid(new Bundle {
        val token = new RobToken(p)
        val pc = UInt(64.W)
        val address = UInt(64.W)
    })))
    val loadResult = IO(Output(Valid(new RobToken(p))))
    val observedLsu = core.backend.lsu
    loadStart.valid := BoringUtils.bore(observedLsu.io.start.valid) &&
        BoringUtils.bore(observedLsu.io.start.ready) &&
        !BoringUtils.bore(observedLsu.io.start.bits.store) && !BoringUtils.bore(observedLsu.io.start.bits.atomic)
    loadStart.bits.token := BoringUtils.bore(observedLsu.io.start.bits.token)
    loadStart.bits.pc := BoringUtils.bore(observedLsu.io.start.bits.pc)
    loadStart.bits.address := BoringUtils.bore(observedLsu.io.start.bits.address)
    loadResult.valid := BoringUtils.bore(observedLsu.io.complete.valid) &&
        BoringUtils.bore(core.backend.ledger.io.completionAccepted(0)) &&
        !BoringUtils.bore(observedLsu.io.complete.bits.exception)
    loadResult.bits := BoringUtils.bore(observedLsu.io.complete.bits.token)
    // GSIM applies registered state at the beginning of step(). The external
    // instruction device needs the next raw cursor before supplying that step.
    // This is device stimulus, never the expected architectural retirement PC.
    val storeOperandGrant = IO(Output(Bool()))
    val storeAndAluCapture = IO(Output(Bool()))
    val storeCommonRankDiffers = IO(Output(Bool()))
    if (p.earlyStorePreparation) {
        val backend = core.backend
        val grants = BoringUtils.bore(backend.preparedOwners)
        val enqueued = BoringUtils.bore(backend.executionEnqueued)
        val common = Seq(BoringUtils.bore(backend.issueSelector.get.io.second),
            BoringUtils.bore(backend.issueSelector.get.io.first))
        val values = if (!p.lvtPhysicalRegisterFile) {
            VecInit(backend.values.get.map(v => BoringUtils.bore(v)))
        } else {
            // Test-only semantic shadow. Derive authorization independently from
            // the ledger/queue, never from PRF bank/owner/write-port state.
            val shadow = RegInit(VecInit(Seq.fill(p.physicalRegs)(0.U(64.W))))
            val destinations = VecInit(backend.queue.map(q => BoringUtils.bore(q.renamed.destination)))
            val writesRd = VecInit(backend.queue.map(q => BoringUtils.bore(q.renamed.writesRd)))
            for (lane <- 0 until p.completionWidth) {
                val accepted = BoringUtils.bore(backend.ledger.io.completionAccepted(lane))
                val completion = BoringUtils.bore(backend.ledger.io.complete(lane).bits)
                val index = Mux(accepted, completion.token.index, 0.U)
                when(accepted && !completion.exception && writesRd(index)) {
                    shadow(destinations(index)) := completion.data
                }
            }
            shadow
        }
        val sources1 = VecInit(backend.queue.map(q => BoringUtils.bore(q.renamed.source1)))
        val sources2 = VecInit(backend.queue.map(q => BoringUtils.bore(q.renamed.source2)))
        val storeFlags = VecInit(backend.queue.map(q => BoringUtils.bore(q.request.store)))
        val owners = backend.earlyStorePayloads.get._1.map(o => BoringUtils.bore(o))
        val payloads = backend.earlyStorePayloads.get._2.map(o => BoringUtils.bore(o))
        val accepted = grants.reduce(_ | _)
        storeOperandGrant := accepted.orR
        storeAndAluCapture := accepted.orR && enqueued.asUInt.orR
        val commonOldestStore = (common(1) & storeFlags.asUInt).orR
        storeCommonRankDiffers := grants(0).orR && !commonOldestStore
        for (rank <- 0 until 2; slot <- 0 until p.robEntries) {
            when(accepted(slot) && owners(rank)(slot)) {
                val left = chisel3.util.Mux1H((0 until p.physicalRegs).map(r =>
                    (sources1(slot) === r.U) -> values(r)))
                val right = chisel3.util.Mux1H((0 until p.physicalRegs).map(r =>
                    (sources2(slot) === r.U) -> values(r)))
                assert(payloads(rank).base === left && payloads(rank).data === right,
                    "granted store must capture raw PRF operands without ALU forwarding")
                assert(payloads(rank).token.index === slot.U,
                    "granted store token must remain paired with shared raw operands")
            }
        }
    } else {
        storeOperandGrant := false.B
        storeAndAluCapture := false.B
        storeCommonRankDiffers := false.B
    }
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
    val base = ThroughputPerfConfig.params(profile)
    ChiselStage.emitCHIRRTLFile(new ThroughputPerfGsim(base.copy(
        registeredLoadIssueForwarding = base.registeredLoadIssueForwarding || args.contains("load-issue-forwarding"),
        bankedRobPayload = args.drop(2).contains("banked-rob"),
        sharedStoreOperandReads = args.drop(2).contains("shared-store-reads"),
        lvtPhysicalRegisterFile = args.drop(2).contains("lvt-prf"),
        bankedIssuePayload = args.drop(2).contains("banked-issue-payload"),
        bankedFetchHints = args.drop(2).contains("banked-fetch-hints"),
        ownerLocalIssueReady = args.drop(2).contains("owner-local-issue-ready"))),
        Array("--target-dir", args.head))
}
