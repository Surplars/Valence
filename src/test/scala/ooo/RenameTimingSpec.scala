package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class RenameTimingSpec extends AnyFunSuite {
    test("rename candidate inherits execute cuts without widening or added state") {
        val p = BoardSocConfig.timingParams("staged-rename")
        assert(p == BoardSocConfig.timingParams("staged-execute").copy(earlyRenameDestinations = true,
            parallelPrfReadyUpdates = true, stablePredictionMetadata = true))
        assert(p.issueWidth == 2 && p.robEntries == 16 && p.physicalRegs == 48)
        assert(BoardSocConfig.timingProfile == "early-issue")
        intercept[IllegalArgumentException] { BoardSocConfig.timingParams("staged-rename", 4) }
        for ((width, registers) <- Seq((1, 36), (2, 48), (4, 64), (6, 96))) {
            for (rtl <- Seq(ChiselStage.emitCHIRRTL(new RenameDestinationCandidates(width, registers)),
                ChiselStage.emitCHIRRTL(new PhysicalReadyUpdate(registers, width + 1, width)))) {
                assert(!rtl.linesIterator.exists(_.trim.startsWith("reg ")))
            }
        }
    }
    test("fresh destination contract cannot silently change alias ownership") {
        intercept[IllegalArgumentException] { OooParams(earlyRenameDestinations = true) }
        intercept[IllegalArgumentException] {
            OooParams(parallelRenameAdmission = true, earlyRenameDestinations = true, moveAlias = true)
        }
        val rtl = ChiselStage.emitCHIRRTL(new RenameRob(
            OooParams(parallelRenameAdmission = true, earlyRenameDestinations = true)))
        assert(rtl.contains("module RenameDestinationCandidates"))
    }
}
