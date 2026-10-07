package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class ControlHeadsTimingSpec extends AnyFunSuite {
    test("three control heads remain opt-in and preserve two-issue geometry") {
        val old = BoardSocConfig.timingParams("staged-rom-boundary")
        val next = BoardSocConfig.timingParams("staged-control-heads")
        assert(next == old.copy(registeredTranslationHeads = true, registeredPredictionTraining = true,
            parallelMemoryPayload = true, parallelPacketPmp = true))
        assert(next.renameWidth == 2 && next.robEntries == 16 && next.physicalRegs == 48)
        assert(!OooParams().registeredTranslationHeads && !OooParams().registeredPredictionTraining)
        intercept[IllegalArgumentException](OooParams(registeredTranslationHeads = true))
        intercept[IllegalArgumentException](OooParams(parallelMemoryPayload = true))
        intercept[IllegalArgumentException](OooParams(parallelPacketPmp = true))
    }
    test("packet PMP and memory rank selection add no pipeline registers") {
        val pmp = ChiselStage.emitCHIRRTL(new PacketFetchPmp(16, 2))
        val ranks = ChiselStage.emitCHIRRTL(new MemoryPreparationSelector(OooParams(robEntries = 16), true))
        assert(!pmp.linesIterator.exists(_.trim.startsWith("reg ")))
        assert(!ranks.linesIterator.exists(_.trim.startsWith("reg ")))
        assert(ranks.contains("CircularIssueSelector") && ranks.contains("firstOwner"))
    }
    test("checked translation and registered responses expose direct register heads") {
        val p = BoardSocConfig.timingParams("staged-control-heads").copy(
            machineSystem = true, pmpEntries = 8, virtualMemoryLevels = 3)
        val translation = ChiselStage.emitCHIRRTL(new DataTranslationAdapter(p, registerCheckedRequests = true))
        assert(translation.linesIterator.exists(line =>
            line.trim.startsWith("inst checked") && line.contains("of TwoEntryRegisterQueue")))
        val response = ChiselStage.emitCHIRRTL(new DataResponseBuffer(registerPayload = true, registerHead = true))
        assert(response.contains("TwoEntryRegisterQueue") && !response.contains("smem "))
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new DataResponseBuffer(registerHead = true))
        }
    }
    test("predictor packet captures raw commit fields before training arithmetic") {
        for (width <- Seq(2, 4)) {
            val p = OooParams(renameWidth = width, commitWidth = width, completionWidth = width,
                compressedInstructions = true, registeredPredictionTraining = true)
            val staged = ChiselStage.emitCHIRRTL(new CommitPredictionTraining(p))
            val direct = ChiselStage.emitCHIRRTL(new CommitPredictionTraining(p.copy(registeredPredictionTraining = false)))
            assert(staged.contains("reg packet_payload") && staged.contains("nextPc"))
            assert(!direct.contains("reg packet_payload"))
        }
    }
}
