package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class StagedFabricSpec extends AnyFunSuite {
    test("batch profile remains two-wide and does not replace the stable default") {
        val p = BoardSocConfig.timingParams("staged-fabric")
        assert(BoardSocConfig.timingProfile == "early-issue")
        assert(p.renameWidth == 2 && p.issueWidth == 2 && p.commitWidth == 2)
        assert(p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 2 && p.storeBufferEntries == 2)
        assert(p.registeredLoadReplay && p.registeredRobRetirement && p.registeredMemoryAddress)
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new MachinePlatform(stagedMemoryFabric = true)) }
    }
    test("parallel decode rejects overlap and supports the exact 40-byte DMA window") {
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new ParallelRegisterRouter(Seq((BigInt(0), BigInt(16)), (BigInt(8), BigInt(16)))))
        }
        val rtl = ChiselStage.emitCHIRRTL(new StagedFabricGsim)
        assert(rtl.contains("module ParallelRegisterRouter") && rtl.contains("module DataRequestBuffer"))
    }
    test("request boundary cannot use a single-entry stall bubble implementation") {
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new DataRequestBuffer(1)) }
        assert(ChiselStage.emitCHIRRTL(new DataRequestBuffer()).contains("downstreamRequestCpu"))
    }
    test("checked translation requests preserve the fault and response-owner boundary") {
        val p = OooParams(machineSystem = true, virtualMemoryLevels = 3, pmpEntries = 16)
        val rtl = ChiselStage.emitCHIRRTL(new DataTranslationAdapter(p, registerCheckedRequests = true))
        assert(rtl.contains("module Queue2_CheckedDataRequest"))
        assert(rtl.contains("module Queue8_TranslationResponseOwner"))
    }
}
