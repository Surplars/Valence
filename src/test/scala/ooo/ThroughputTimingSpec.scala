package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class ThroughputTimingSpec extends AnyFunSuite {
    test("fault-aware raw rename budgets scalar alternatives without adding state") {
        val p = OooParams(robEntries = 16, physicalRegs = 40, compressedInstructions = true,
            moveAlias = true, tentativeRenameSources = true)
        intercept[IllegalArgumentException](p.copy(renameWidth = 4))
        val candidates = ChiselStage.emitCHIRRTL(new FaultAwareRenameCandidates(p))
        assert(candidates.contains("sources") && candidates.contains("capacity") && candidates.contains("faults"))
        assert(!candidates.linesIterator.exists(_.trim.matches("reg(reset)? .*")) && !candidates.contains("smem "))
        val initialization = ChiselStage.emitCHIRRTL(new FaultAwareAllocationReady(p))
        assert(initialization.contains("sources") && initialization.contains("reserve") && initialization.contains("wake"))
        assert(!initialization.linesIterator.exists(_.trim.matches("reg(reset)? .*")))
        val precomputed = ChiselStage.emitCHIRRTL(new OwnerOperandReady(p, precomputedAllocationReady = true))
        val legacy = ChiselStage.emitCHIRRTL(new OwnerOperandReady(p))
        assert(precomputed.contains("flip allocationReady1") && precomputed.contains("flip allocationReady2"))
        assert(!legacy.contains("flip allocationReady1") && !legacy.contains("flip allocationReady2"),
            "legacy owner-ready top-level ports must remain unchanged")
    }
    test("dual pipeline candidate preserves geometry and remains opt-in") {
        val previous = BoardSocConfig.timingParams("staged-control-heads")
        val next = BoardSocConfig.timingParams("staged-throughput")
        assert(next == previous.copy(registeredIssueExecute = true, registeredFetchPacket = true,
            fastHeadTrapRecovery = true, fastHeadSystemRecovery = true,
            tentativeRenameSources = true, sharedPhysicalSourceDecode = true, ownerLocalOperandReady = true,
            earlyStorePreparation = true, parallelMulDivDispatch = true, registeredMulDivOperands = true))
        assert(next.renameWidth == 2 && next.commitWidth == 2 && next.completionWidth == 2)
        assert(next.robEntries == 16 && next.physicalRegs == 48 && next.memoryEntries == 2)
        assert(!OooParams().registeredIssueExecute && !OooParams().registeredFetchPacket)
        assert(!OooParams().fastHeadTrapRecovery && !previous.fastHeadTrapRecovery)
        assert(!OooParams().fastHeadSystemRecovery && !previous.fastHeadSystemRecovery)
        assert(!OooParams().tentativeRenameSources && !previous.tentativeRenameSources)
        assert(!OooParams().sharedPhysicalSourceDecode && !previous.sharedPhysicalSourceDecode)
        assert(!next.machineSystem, "timing parameters are constructed before MachinePlatform enables the system unit")
        assert(!OooParams().ownerLocalOperandReady && !OooParams().earlyStorePreparation &&
            !OooParams().parallelMulDivDispatch)
        assert(!OooParams().registeredMulDivOperands && next.registeredMulDivOperands)
        assert(!next.oneHotPhysicalOperands, "specialized memory/M operand networks must not replace all ALU reads")
        assert(BoardSocConfig.timingProfile == "early-issue")
    }

    test("bare/direct-machine profile copies retain the complete authorization candidate") {
        val p = ThroughputPerfConfig.params("staged-throughput")
        assert(p.fastHeadSystemRecovery && p.tentativeRenameSources && p.sharedPhysicalSourceDecode)
        val old = ThroughputPerfConfig.params("staged-control-heads")
        assert(!old.fastHeadSystemRecovery && !old.tentativeRenameSources && !old.sharedPhysicalSourceDecode)
    }

    test("execution stages reject unsupported ownership contracts") {
        val p = BoardSocConfig.timingParams("staged-throughput")
        intercept[IllegalArgumentException](OooParams(registeredIssueExecute = true))
        intercept[IllegalArgumentException](p.copy(moveAlias = true))
        intercept[IllegalArgumentException](p.copy(precompleteMispredictedBranch = false))
        intercept[IllegalArgumentException](p.copy(registeredRobRetirement = false))
        intercept[IllegalArgumentException](OooParams(fastHeadTrapRecovery = true))
        intercept[IllegalArgumentException](OooParams(fastHeadSystemRecovery = true))
        intercept[IllegalArgumentException](OooParams(sharedPhysicalSourceDecode = true))
        intercept[IllegalArgumentException](p.copy(parallelRecoveryAdmission = false))
        intercept[IllegalArgumentException](OooParams(ownerLocalOperandReady = true))
        intercept[IllegalArgumentException](OooParams(earlyStorePreparation = true))
        intercept[IllegalArgumentException](OooParams(parallelMulDivDispatch = true))
        intercept[IllegalArgumentException](p.copy(loadCompletionBypass = true))
        intercept[IllegalArgumentException](p.copy(mulWordPreviewBypass = true))
        intercept[IllegalArgumentException](p.copy(parallelPrfReadyUpdates = false))
        val storeOnly = p.copy(ownerLocalOperandReady = false, parallelMulDivDispatch = false,
            sharedPhysicalSourceDecode = false)
        intercept[IllegalArgumentException](storeOnly.copy(loadCompletionBypass = true))
        intercept[IllegalArgumentException](storeOnly.copy(mulWordPreviewBypass = true))
    }

    test("operand stage has registered payload and cancellation-independent input credit") {
        val text = ChiselStage.emitCHIRRTL(new IssueExecuteStage(128))
        assert(text.contains("regreset occupied") && text.contains("regreset payload"))
        assert(text.contains("cancel") && !text.contains("smem "))
        val creditNodes = text.linesIterator.filter(_.trim.startsWith("node _io_enq_ready_")).mkString("\n")
        assert(creditNodes.contains("eq(occupied") && creditNodes.contains("io.deq.ready"))
        assert(!creditNodes.contains("io.cancel"))
        assert(text.linesIterator.exists(_.trim.startsWith("connect io.enq.ready, _io_enq_ready_")))
    }

    test("fetch reservoir keeps raw metadata before compressed decode") {
        for (compressed <- Seq(false, true)) {
            val text = ChiselStage.emitCHIRRTL(new RegisteredFetchPacket(2, compressed, BigInt("80000000", 16)))
            assert(text.contains("reg slots") && text.contains("regreset count"))
            assert(text.contains("faultAddress") && text.contains("pageFault"))
            assert(text.contains("nextFetchPc") && !text.contains("smem "))
        }
    }

    test("store candidates expose only registered owner facts and no late ALU credit") {
        val text = ChiselStage.emitCHIRRTL(
            new StorePreparationEligibility(BoardSocConfig.timingParams("staged-throughput")))
        assert(text.contains("operandReady1") && text.contains("operandReady2") &&
            text.contains("addressKnown") && text.contains("branchRedirect"))
        assert(!text.linesIterator.exists(_.trim.matches("reg(reset)? .*")))
        for (forbidden <- Seq("executionWake", "deq", "complete", "kill", "readyToExecute", "aluPromise"))
            assert(!text.contains(forbidden), s"store candidate interface must not depend on $forbidden")
    }

    test("side-unit cuts keep readiness state local and payload selection combinational") {
        val p = BoardSocConfig.timingParams("staged-throughput")
        val ready = ChiselStage.emitCHIRRTL(new OwnerOperandReady(p))
        assert(ready.contains("regreset ready1") && ready.contains("regreset ready2"))
        assert(ready.contains("allocate") && ready.contains("reserve") && ready.contains("wake"))
        val split = ChiselStage.emitCHIRRTL(new SplitMulDivSelector(p))
        assert(split.contains("CircularIssueSelector") && split.contains("available") && split.contains("grant"))
        assert(!split.linesIterator.exists(_.trim.matches("reg(reset)? .*")))
    }
}
