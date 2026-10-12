package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class RegisteredExecutionOperandConfigSpec extends AnyFunSuite {
    test("direct registered execution operands default off and require their capture boundary") {
        assert(!OooParams().directRegisteredExecutionOperands)
        intercept[IllegalArgumentException] { OooParams(directRegisteredExecutionOperands = true) }
        val serial = OooParams(registeredBranchRedirect = true, registeredRobRetirement = true,
            precompleteMispredictedBranch = true, registeredIssueExecute = true,
            directRegisteredExecutionOperands = true)
        assert(!serial.parallelIssuePayload && !serial.parallelIssueRanks)
        for (banked <- Seq(false, true)) {
            assert(serial.copy(bankedIssuePayload = banked).directRegisteredExecutionOperands)
            for (parallel <- Seq(false, true)) {
                val p = RegisteredExecutionOperandProof.params(parallel, banked)
                    .copy(directRegisteredExecutionOperands = true)
                assert(p.registeredIssueExecute && p.completionWidth == 2)
                intercept[IllegalArgumentException] { p.copy(registeredIssueExecute = false) }
            }
        }
    }
}
