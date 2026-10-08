package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class OwnerLocalIssueReadySpec extends AnyFunSuite {
    test("local issue readiness is opt-in and requires the proven mirror/promise contract") {
        val base = BoardSocConfig.timingParams("staged-fetch-turnover")
        assert(!base.ownerLocalIssueReady)
        assert(base.copy(ownerLocalIssueReady = true).copy(ownerLocalIssueReady = false) == base)
        intercept[IllegalArgumentException] { OooParams(ownerLocalIssueReady = true) }
        intercept[IllegalArgumentException] { base.copy(ownerLocalIssueReady = true, ownerLocalOperandReady = false) }
        intercept[IllegalArgumentException] { base.copy(ownerLocalIssueReady = true, registeredIssueExecute = false) }
    }
    test("local cone removes all dynamic physical-ready reads without a new register") {
        val global = ChiselStage.emitCHIRRTL(new IssueReadyCone(false))
        val local = ChiselStage.emitCHIRRTL(new IssueReadyCone(true))
        assert("dshr\\(io.physical,".r.findAllIn(global).length == 32, global)
        assert(!local.contains("dshr(io.physical,"), local)
        assert(!local.contains(" reg ") && !local.contains("cmem") && !local.contains("smem"), local)
    }
}
