package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class MemoryCapacitySpec extends AnyFunSuite {
    test("opt-in four-slot profile changes precisely one explicit parameter") {
        val name = BoardSocConfig.memoryCapacityProfile
        val baseline = BoardSocConfig.timingParams("staged-fetch-turnover")
        val candidate = BoardSocConfig.timingParams(name)
        assert(candidate == baseline.copy(memoryEntries = 4))
        assert(BoardSocConfig.timingProfile == "early-issue")
        for (profile <- BoardSocConfig.timingProfiles - name) {
            assert(BoardSocConfig.timingParams(profile).memoryEntries == 2)
        }
        assert(candidate.renameWidth == 2 && candidate.commitWidth == 2 && candidate.completionWidth == 2)
        assert(candidate.robEntries == 16 && candidate.physicalRegs == 48 && candidate.branchPredictorEntries == 32)
        assert(candidate.storeBufferEntries == 2 && !candidate.registeredLoadIssueForwarding && !candidate.loadCompletionBypass)
        val board = BoardSocConfig.boardParams(name, externalDdr = true, isa = "rv64gc",
            ddrMemoryBytes = BigInt(1) << 31)
        val before = BoardSocConfig.boardParams("staged-fetch-turnover", externalDdr = true, isa = "rv64gc",
            ddrMemoryBytes = BigInt(1) << 31)
        assert(board == before.copy(memoryEntries = 4))
        assert(board.fpConfig.complete && board.speculativeRamBytes == (BigInt(1) << 31))
        assert(ThroughputPerfConfig.params(name) ==
            ThroughputPerfConfig.params("staged-fetch-turnover").copy(memoryEntries = 4))
        intercept[IllegalArgumentException] { BoardSocConfig.timingParams(name, 4) }
    }
}
