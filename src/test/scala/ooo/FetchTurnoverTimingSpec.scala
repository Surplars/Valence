package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class FetchTurnoverTimingSpec extends AnyFunSuite {
    test("fetch turnover is isolated from load forwarding and existing profiles") {
        val baseline = BoardSocConfig.timingParams("staged-fetch-feedback")
        val candidate = BoardSocConfig.timingParams("staged-fetch-turnover")
        assert(candidate == baseline.copy(fetchReplyTurnover = true, fetchIdentityTranslation = true))
        assert(candidate.issueWidth == 2 && !candidate.registeredLoadIssueForwarding && !candidate.loadCompletionBypass)
        assert(candidate.registeredTranslationHeads && candidate.registeredTranslatedResponses)
        assert(candidate.registeredFetchWindow && candidate.registeredFetchPacket && candidate.registeredFabricBoundary)
        for (profile <- BoardSocConfig.timingProfiles -- Set("staged-fetch-turnover", BoardSocConfig.memoryCapacityProfile)) {
            val previous = BoardSocConfig.timingParams(profile)
            assert(!previous.fetchReplyTurnover && !previous.fetchIdentityTranslation)
        }
        assert(!OooParams().fetchReplyTurnover && !OooParams().fetchIdentityTranslation)
    }

    test("each optimization requires registered translation heads and can be isolated") {
        intercept[IllegalArgumentException] { OooParams(fetchReplyTurnover = true) }
        intercept[IllegalArgumentException] { OooParams(fetchIdentityTranslation = true) }
        val base = BoardSocConfig.timingParams("staged-fetch-feedback")
        assert(base.copy(fetchReplyTurnover = true).fetchReplyTurnover)
        assert(base.copy(fetchIdentityTranslation = true).fetchIdentityTranslation)
        intercept[IllegalArgumentException] {
            BoardSocConfig.timingParams("staged-fetch-turnover").copy(registeredTranslationHeads = false)
        }
    }

    test("turnover preserves the two-issue RV64GC two-GiB board geometry") {
        val before = BoardSocConfig.boardParams("staged-fetch-feedback", externalDdr = true,
            isa = "rv64gc", ddrMemoryBytes = BigInt(1) << 31)
        val after = BoardSocConfig.boardParams("staged-fetch-turnover", externalDdr = true,
            isa = "rv64gc", ddrMemoryBytes = BigInt(1) << 31)
        assert(after == before.copy(fetchReplyTurnover = true, fetchIdentityTranslation = true))
        assert(after.fpConfig.complete && after.issueWidth == 2 && after.speculativeRamBytes == (BigInt(1) << 31))
        assert(after.pmpEntries == 16 && after.virtualMemoryLevels == 3)
    }
}
