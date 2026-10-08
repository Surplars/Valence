package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.BoardSocConfig

class VirtualLoadBoardConfigSpec extends AnyFunSuite {
    test("board defaults retain serial virtual-load policy") {
        assert(!BoardSocConfig.boardParams("staged-fetch-turnover", externalDdr = true,
            isa = "rv64gc", ddrMemoryBytes = BigInt(1) << 31).virtualRamLoadPrecheck)
    }

    test("selected board enables only the explicit virtual-load option") {
        val baseline = BoardSocConfig.boardParams("staged-fetch-turnover", externalDdr = true,
            isa = "rv64gc", ddrMemoryBytes = BigInt(1) << 31,
            identityDataFlow = true, dataNextLinePrefetch = true)
        val candidate = BoardSocConfig.boardParams("staged-fetch-turnover", externalDdr = true,
            isa = "rv64gc", ddrMemoryBytes = BigInt(1) << 31,
            identityDataFlow = true, dataNextLinePrefetch = true, virtualRamLoadPrecheck = true)
        assert(candidate == baseline.copy(virtualRamLoadPrecheck = true))
        assert(candidate.issueWidth == 2 && candidate.memoryEntries == 2)
        assert(candidate.virtualMemoryLevels == 3 && candidate.pmpEntries == 16)
    }

    test("opt-in does not silently upgrade an unstaged board profile") {
        intercept[IllegalArgumentException] {
            BoardSocConfig.boardParams("early-issue", externalDdr = true,
                isa = "rv64gc", virtualRamLoadPrecheck = true)
        }
    }
}
