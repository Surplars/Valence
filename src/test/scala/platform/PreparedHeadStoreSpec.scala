package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

class PreparedHeadStoreSpec extends AnyFunSuite {
    test("prepared head-store experiment changes one flag and has its own validated memory identity") {
        val control = CommonA1RebuildProfile.FullR1M3CheckedFlow.config
        val candidate = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRow.config
        assert(!OooParams().preparedHeadStoreOperands)
        assert(!FpgaNextConfig.Selected.preparedHeadStoreOperands)
        assert(!CommonCpuProfile.A1.fpga.preparedHeadStoreOperands)
        assert(candidate == control.copy(preparedHeadStoreOperands = true))
        assert(candidate.coreParams == control.coreParams.copy(preparedHeadStoreOperands = true))
        assert(candidate.cache == control.cache && candidate.ddr == control.ddr)
        assert(candidate.name != control.name)
        assert(CommonA1RebuildProfile.named("full-r1-m3-checked-flow-store-row") ==
            CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRow)
        CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRow.memoryProfile.get.validate(candidate, CommonCpuTilePortParams())
        for (profile <- CommonA1RebuildProfile.all.filterNot(_.preparedHeadStore)) {
            assert(!profile.config.preparedHeadStoreOperands)
            profile.memoryProfile.foreach { policy =>
                intercept[IllegalArgumentException] { policy.validate(candidate, CommonCpuTilePortParams()) }
            }
        }
        intercept[IllegalArgumentException] {
            CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRow.memoryProfile.get.validate(control, CommonCpuTilePortParams())
        }
        intercept[IllegalArgumentException] { candidate.managedBoard() }
    }

    test("prepared numerical rows cannot silently enable historical ownership or preparation shortcuts") {
        val c = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRow.config
        intercept[IllegalArgumentException] { c.copy(combinedCheckedDataFlow = false) }
        intercept[IllegalArgumentException] { c.copy(completedCanonicalStoreForwarding = false) }
        intercept[IllegalArgumentException] { c.copy(residentMemoryPayloadReuse = true) }
        intercept[IllegalArgumentException] { c.copy(preparedStoreLookahead = true) }
        intercept[IllegalArgumentException] { c.copy(postedStoreMerge = true) }
        intercept[IllegalArgumentException] { c.copy(taggedStoreReturns = true) }
        val p = c.coreParams
        intercept[IllegalArgumentException] { p.copy(parallelMemoryPreparation = false) }
        intercept[IllegalArgumentException] { p.copy(parallelMemoryPayload = false) }
        intercept[IllegalArgumentException] { p.copy(earlyStorePreparation = false) }
        intercept[IllegalArgumentException] { p.copy(registeredLoadIssueForwarding = false) }
        intercept[IllegalArgumentException] { p.copy(earlyRecoveryIssueBlock = false) }
        intercept[IllegalArgumentException] { p.copy(pendingVirtualStoreProof = true) }
    }

    test("row shape is parameterized and exposes only registered numerical preparation") {
        val p = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRow.config.coreParams
        assert(p.robBits + p.tagBits + 64 + 64 + 2 + 1 == 199)
        val fir = ChiselStage.emitCHIRRTL(new PreparedHeadStoreOperands(p))
        assert(fir.contains("prepared head store consume requires exact full token"))
        assert(fir.contains("prepared head store consume forbidden during flush"))
        assert(!fir.contains("physicalAddress") && !fir.contains("translationEpoch") && !fir.contains("memoryBusy"))
        val compact = ChiselStage.emitCHIRRTL(new PreparedHeadStoreOperands(OooParams(robEntries = 8, tagBits = 9)))
        assert(compact.contains("tag : UInt<9>"))
        assert(compact.contains("index : UInt<3>"))
    }
}
