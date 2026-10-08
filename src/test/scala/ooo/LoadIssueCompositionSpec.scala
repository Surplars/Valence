package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.BoardSocConfig

class LoadIssueCompositionSpec extends AnyFunSuite {
    test("typed load-result forwarding composes with turnover without changing other parameters") {
        val baseline = BoardSocConfig.boardParams("staged-fetch-turnover", externalDdr = true,
            isa = "rv64gc", ddrMemoryBytes = BigInt(1) << 31)
        val candidate = BoardSocConfig.boardParams("staged-fetch-turnover", externalDdr = true,
            isa = "rv64gc", ddrMemoryBytes = BigInt(1) << 31, loadIssueForwarding = Some(true))
        assert(candidate == baseline.copy(registeredLoadIssueForwarding = true))
        assert(candidate.fetchReplyTurnover && candidate.fetchIdentityTranslation)
        assert(candidate.registeredIssueExecute && !candidate.loadCompletionBypass)
        assert(candidate.memoryEntries == 2 && candidate.issueWidth == 2 && candidate.fpConfig.complete)
        assert(candidate.speculativeRamBytes == (BigInt(1) << 31))
    }
    test("None preserves every existing profile and explicit false can disable an opt-in profile") {
        for (profile <- BoardSocConfig.timingProfiles) {
            val inherited = BoardSocConfig.boardParams(profile)
            assert(inherited.registeredLoadIssueForwarding ==
                BoardSocConfig.timingParams(profile).registeredLoadIssueForwarding)
        }
        assert(BoardSocConfig.boardParams("staged-load-issue").registeredLoadIssueForwarding)
        assert(!BoardSocConfig.boardParams("staged-load-issue", loadIssueForwarding = Some(false))
            .registeredLoadIssueForwarding)
        assert(!BoardSocConfig.boardParams("staged-fetch-turnover").registeredLoadIssueForwarding)
    }
    test("forwarding still requires registered execution rather than a broad combinational bypass") {
        intercept[IllegalArgumentException] {
            BoardSocConfig.boardParams("early-issue", loadIssueForwarding = Some(true))
        }
        val candidate = BoardSocConfig.boardParams("staged-fetch-turnover", loadIssueForwarding = Some(true))
        intercept[IllegalArgumentException] { candidate.copy(loadCompletionBypass = true) }
    }
}
