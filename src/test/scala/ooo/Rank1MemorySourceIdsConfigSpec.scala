package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class Rank1MemorySourceIdsConfigSpec extends AnyFunSuite {
    private val off = OooParams(robEntries = 16, physicalRegs = 48,
        registeredMemoryAddress = true, parallelMemoryPreparation = true,
        parallelMemoryPayload = true, compactMemoryOperandSelect = true)

    test("rank1 direct IDs are default off and change no other parameter") {
        assert(!OooParams().directRank1MemorySourceIds)
        assert(!FpgaNextConfig.Selected.directRank1MemorySourceIds)
        val on = off.copy(directRank1MemorySourceIds = true)
        assert(on.copy(directRank1MemorySourceIds = false) == off)
        assert(on.issueWidth == 2 && on.physicalRegs == 48 && on.robEntries == 16)
        // The optimization does not require a new PRF topology or payload RAM.
        assert(on.copy(lvtPhysicalRegisterFile = true).directRank1MemorySourceIds)
        assert(on.copy(bankedIssuePayload = true).directRank1MemorySourceIds)
    }

    test("every owner-masked preparation prerequisite fails closed") {
        val attempts = Seq[() => OooParams](
            () => off.copy(registeredMemoryAddress = false, directRank1MemorySourceIds = true),
            () => off.copy(parallelMemoryPreparation = false, directRank1MemorySourceIds = true),
            () => off.copy(parallelMemoryPayload = false, directRank1MemorySourceIds = true),
            () => off.copy(compactMemoryOperandSelect = false, directRank1MemorySourceIds = true),
            () => off.copy(memoryProofFrontier = true, directRank1MemorySourceIds = true))
        for (attempt <- attempts) {
            val error = intercept[IllegalArgumentException] { attempt() }
            assert(error.getMessage.contains("direct rank-1 memory source IDs"))
        }
    }

    test("board option forwarding preserves all other switches and resources") {
        val base = FpgaNextConfig.fromOptions(Set("--selected"), defaultSelected = false)
        val on = FpgaNextConfig.fromOptions(Set("--selected", "--direct-rank1-memory-source-ids"),
            defaultSelected = false)
        assert(on.directRank1MemorySourceIds && on.coreParams.directRank1MemorySourceIds)
        assert(on.copy(directRank1MemorySourceIds = false) == base)
        assert(on.coreParams.copy(directRank1MemorySourceIds = false) == base.coreParams)
        assert(on.cache == base.cache && on.storage == base.storage && on.ddr == base.ddr)
        intercept[IllegalArgumentException] {
            FpgaNextConfig.fromOptions(Set("--direct-rank1-memory-source-ids=1"), defaultSelected = false)
        }
    }

    test("otherwise-supported proof-frontier profile rejects direct IDs") {
        val options = PostedPrefetchBoardProfiles.options("head-offer", "on") ++
            Set("--canonical-virtual-store-overlap", "--rob-entries=64", "--physical-regs=64",
                "--memory-proof-frontier")
        val frontier = FpgaNextConfig.fromOptions(options, defaultSelected = false).coreParams
        assert(frontier.memoryProofFrontier && !frontier.directRank1MemorySourceIds)
        val error = intercept[IllegalArgumentException] { frontier.copy(directRank1MemorySourceIds = true) }
        assert(error.getMessage.contains("direct rank-1 memory source IDs"))
    }
}
