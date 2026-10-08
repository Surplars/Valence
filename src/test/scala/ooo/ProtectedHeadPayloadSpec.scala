package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class ProtectedHeadPayloadSpec extends AnyFunSuite {
    test("sharing is explicit and retains exact selected geometry and protected execution") {
        val p = FpgaNextConfig.Candidate.coreParams
        assert(!p.shareProtectedHeadPayload)
        assert(p.copy(shareProtectedHeadPayload = true).copy(shareProtectedHeadPayload = false) == p)
        intercept[IllegalArgumentException] { p.copy(shareProtectedHeadPayload = true, bankedIssuePayload = false) }
        intercept[IllegalArgumentException] { p.copy(shareProtectedHeadPayload = true, compressedInstructions = false) }
        intercept[IllegalArgumentException] { p.copy(shareProtectedHeadPayload = true, fastHeadSystemRecovery = false) }
        intercept[IllegalArgumentException] { OooParams(shareProtectedHeadPayload = true) }
    }
}
