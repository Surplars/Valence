package ooo

import soc.core.ooo._

/** Inspect the exact constructed backend; no observer state or test ports. */
object MemoryPreparationLocalityActualAudit {
    def captureBackend(backend: IntegerBackend, expected: OooParams): Map[String, Any] = {
        require(backend.p == expected, "actual memory preparation backend profile differs")
        require(backend.memoryPreparationHeadOwner.nonEmpty == expected.memoryPreparationHeadMask,
            "actual memory preparation head-owner branch differs")
        require(backend.issueHeadMask.nonEmpty == expected.registeredIssueHeadMask,
            "actual registered head-mask boundary differs")
        val width = backend.memoryPreparationHeadOwner.map(_.getWidth).getOrElse(0)
        require(width == (if (expected.memoryPreparationHeadMask) expected.robEntries else 0))
        require(backend.memoryPreparationDirectSourceRanks ==
            Seq(expected.directRank0MemorySourceIds, expected.directRank1MemorySourceIds),
            "actual direct memory source-ID branches differ")
        Map("schema" -> "actual-memory-preparation-locality-v1", "scope" -> "actual-constructor-only",
            "memoryPreparationHeadMask" -> backend.memoryPreparationHeadOwner.nonEmpty,
            "headOwnerWidth" -> width, "registeredIssueHeadMask" -> backend.issueHeadMask.nonEmpty,
            "directSourceRanks" -> backend.memoryPreparationDirectSourceRanks,
            "robEntries" -> backend.p.robEntries, "physicalRegs" -> backend.p.physicalRegs,
            "tagBits" -> backend.p.tagBits, "coreFields" -> backend.p.productArity,
            "physicalQualification" -> false)
    }

    def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
        val core = platform.core.core.core
        require(core.p == expected.coreParams, "actual core memory preparation configuration differs")
        captureBackend(core.backend, core.p)
    }
}
