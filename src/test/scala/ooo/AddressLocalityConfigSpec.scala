package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class AddressLocalityConfigSpec extends AnyFunSuite {
    test("locality switches default off and append without changing existing fields") {
        val p = OooParams()
        val c = FpgaNextConfig.Selected
        assert(!p.memoryPreparationHeadMask && !p.directRank0MemorySourceIds)
        assert(!c.memoryPreparationHeadMask && !c.directRank0MemorySourceIds)
        assert(c.productElementNames.toSeq.slice(79, 81) ==
            Seq("memoryPreparationHeadMask", "directRank0MemorySourceIds"))
        assert(p.productElementNames.toSeq.slice(164, 166) ==
            Seq("memoryPreparationHeadMask", "directRank0MemorySourceIds"))
        PlacedTimingProfileBridge.requireShape(c)
    }

    test("both options reach the complete core without changing service or capacity") {
        val base = FpgaNextConfig.fromOptions(Set("--selected"), defaultSelected = false)
        val options = Set("--selected", "--memory-preparation-head-mask", "--direct-rank0-memory-source-ids")
        FpgaNextProfileOptions.validate(options.toSeq)
        val on = FpgaNextConfig.fromOptions(options, defaultSelected = false)
        assert(on.memoryPreparationHeadMask && on.directRank0MemorySourceIds)
        assert(on.coreParams.memoryPreparationHeadMask && on.coreParams.directRank0MemorySourceIds)
        assert(on.copy(memoryPreparationHeadMask = false, directRank0MemorySourceIds = false) == base)
        assert(on.coreParams.copy(memoryPreparationHeadMask = false, directRank0MemorySourceIds = false) == base.coreParams)
        assert(on.cache == base.cache && on.storage == base.storage && on.ddr == base.ddr)
        assert(on.coreParams.issueWidth == 2 && on.coreParams.commitWidth == 2)
        PlacedTimingProfileBridge.requireShape(on)
        for (flag <- Seq("--memory-preparation-head-mask=1", "--direct-rank0-memory-source-ids=1")) {
            intercept[IllegalArgumentException] {
                FpgaNextConfig.fromOptions(Set("--selected", flag), defaultSelected = false)
            }
        }
    }

    test("head-mask option fails closed without every existing boundary") {
        val base = FpgaNextConfig.Selected.coreParams
        val attempts = Seq[() => OooParams](
            () => base.copy(memoryPreparationHeadMask = true, registeredIssueHeadMask = false),
            () => base.copy(memoryPreparationHeadMask = true, registeredMemoryAddress = false),
            () => base.copy(memoryPreparationHeadMask = true, parallelMemoryPreparation = false))
        for (attempt <- attempts) intercept[IllegalArgumentException] { attempt() }
    }

    test("rank0 direct IDs fail closed outside compact parallel owner masking") {
        val base = OooParams(robEntries = 16, physicalRegs = 48, registeredMemoryAddress = true,
            parallelMemoryPreparation = true, parallelMemoryPayload = true, compactMemoryOperandSelect = true)
        val attempts = Seq[() => OooParams](
            () => base.copy(directRank0MemorySourceIds = true, registeredMemoryAddress = false),
            () => base.copy(directRank0MemorySourceIds = true, parallelMemoryPreparation = false),
            () => base.copy(directRank0MemorySourceIds = true, parallelMemoryPayload = false),
            () => base.copy(directRank0MemorySourceIds = true, compactMemoryOperandSelect = false),
            () => base.copy(directRank0MemorySourceIds = true, memoryProofFrontier = true))
        for (attempt <- attempts) {
            val error = intercept[IllegalArgumentException] { attempt() }
            assert(error.getMessage.contains("direct rank-0 memory source IDs"))
        }
    }
}
