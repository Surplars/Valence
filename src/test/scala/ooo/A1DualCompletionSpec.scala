package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform.CommonCpuProfile

class A1DualCompletionSpec extends AnyFunSuite {
    test("dual-owner is explicit and retains the two-port real A1 geometry") {
        val base = CommonCpuProfile.A1.fpga.coreParams
        assert(base.completionTopology == "legacy")
        val candidate = CommonCpuProfile.A1.fpga.copy(completionTopology = "dual-owner").coreParams
        assert(candidate.copy(completionTopology = "legacy") == base)
        assert(candidate.renameWidth == 2 && candidate.completionWidth == 2 && candidate.commitWidth == 2)
        assert(candidate.robEntries == 16 && candidate.physicalRegs == 48 && candidate.tagBits == 64)
        assert(candidate.machineSystem && candidate.fpEnabled && candidate.virtualMemoryLevels == 3)
        intercept[IllegalArgumentException] { base.copy(completionTopology = "unknown") }
        intercept[IllegalArgumentException] { OooParams(completionTopology = "dual-owner") }
        intercept[IllegalArgumentException] { candidate.copy(sharedLane1OwnerMatch = true) }
        intercept[IllegalArgumentException] { candidate.copy(parallelRecoveryAdmission = false) }
        intercept[IllegalArgumentException] { candidate.copy(retirementIntent = true) }
        intercept[IllegalArgumentException] { candidate.copy(lvtPhysicalRegisterFile = false) }
    }
    test("completion ranking is narrow metadata only with no new state or data stage") {
        val fir = ChiselStage.emitCHIRRTL(new DualCompletionSelector(CommonCpuProfile.A1.fpga.coreParams))
        assert(!fir.contains(" reg ") && !fir.contains("regreset") && !fir.contains("cmem") && !fir.contains("smem"))
        assert(!fir.contains("exception") && !fir.contains("ready") && !fir.contains("data :"))
    }
}
