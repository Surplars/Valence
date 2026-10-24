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
}
