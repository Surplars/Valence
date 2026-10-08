package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class IdentityDataFlowSpec extends AnyFunSuite {
    test("identity data flow is an explicit isolated option with registered boundaries") {
        val base = BoardSocConfig.boardParams("staged-fetch-turnover", externalDdr = true, isa = "rv64gc")
        val fast = BoardSocConfig.boardParams("staged-fetch-turnover", externalDdr = true,
            isa = "rv64gc", identityDataFlow = true)
        assert(!base.identityDataRequestFlow && fast == base.copy(identityDataRequestFlow = true))
        assert(fast.registeredTranslationHeads && fast.registeredTranslatedResponses &&
            fast.registeredMemoryAddress && !fast.loadCompletionBypass)
        assert(fast.memoryEntries == 2 && fast.issueWidth == 2 && fast.fpConfig.complete)
        intercept[IllegalArgumentException] { OooParams(identityDataRequestFlow = true) }
    }
}
