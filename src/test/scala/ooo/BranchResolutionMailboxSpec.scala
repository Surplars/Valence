package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class BranchResolutionMailboxSpec extends AnyFunSuite {
    test("resolution mailbox has its own registered boundary and explicit source capture") {
        val fir = ChiselStage.emitCHIRRTL(new BranchResolutionMailbox(
            OooParams(robEntries = 16, physicalRegs = 48, tagBits = 64)))
        assert(fir.contains("module BranchResolutionMailbox"))
        assert(fir.contains("sourceResolved") && fir.contains("capture"))
        assert(fir.contains("regreset occupied") && fir.contains("regreset payload"))
        assert(!fir.contains("PhysicalRegisterFile") && !fir.contains("RenameRob"))
    }
    test("execution-mailbox is a bounded explicit backend topology, defaulting to WB coupling") {
        val base = soc.platform.CommonCpuProfile.A1.fpga.coreParams
        assert(base.branchResolutionTopology == "writeback-coupled")
        intercept[IllegalArgumentException] { base.copy(branchResolutionTopology = "execution-mailbox") }
        intercept[IllegalArgumentException] { base.copy(branchResolutionTopology = "unknown") }
        val candidate = base.copy(completionTopology = "dual-owner", branchResolutionTopology = "execution-mailbox")
        assert(candidate.copy(completionTopology = "legacy", branchResolutionTopology = "writeback-coupled") == base)
        intercept[IllegalArgumentException] { candidate.copy(registeredLoadReplay = false) }
        val fir = ChiselStage.emitCHIRRTL(new IssueExecuteStage(64, trackResolution = true))
        assert(fir.contains("resolutionCapture") && fir.contains("regreset resolved"))
    }

}
