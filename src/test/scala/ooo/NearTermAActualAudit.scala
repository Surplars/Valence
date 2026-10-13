package ooo

import soc.core.ooo._

/** Read real constructed leaves; profile labels alone do not establish activation. */
object NearTermAActualAudit {
    def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
        PlacedTimingProfileBridge.requireShape(expected)
        val core = platform.core.core.core
        val p = expected.coreParams
        require(core.p == p && core.backend.p == p, "actual complete CPU constructor differs")
        val packet = core.fetchPacket.get
        val fetch = platform.fetchAdapter.get
        val data = platform.core.observationTranslation.get
        val lsu = core.backend.lsu
        require(packet.acceptedPrefixValidation == p.fetchAcceptedPrefixValidation,
            "actual RegisteredFetchPacket did not receive accepted-prefix validation")
        require(fetch.p == p.copy(machineSystem = true, virtualMemoryLevels = 3, pmpEntries = 16) &&
            fetch.p.alignedFetchSinglePage == p.alignedFetchSinglePage,
            "actual instruction translation constructor differs")
        require(data.factorCheckedNextAllowed == p.factorCheckedNextAllowed,
            "actual DataTranslationAdapter did not receive checked hint factoring")
        require(lsu.localTaggedResponseReady == p.localTaggedResponseReady,
            "actual ParallelLoadStoreUnit did not receive local tagged readiness")
        require(lsu.slots.size == expected.lsuEntries, "actual LSU owner count changed")
        Map("schema" -> "actual-near-term-a-v1", "scope" -> "actual-constructor-only",
            "fetchAcceptedPrefixValidation" -> packet.acceptedPrefixValidation,
            "alignedFetchSinglePage" -> fetch.p.alignedFetchSinglePage,
            "factorCheckedNextAllowed" -> data.factorCheckedNextAllowed,
            "localTaggedResponseReady" -> lsu.localTaggedResponseReady,
            "coreFields" -> core.p.productArity, "profileFields" -> expected.productArity,
            "tagBits" -> p.tagBits, "lsuOwners" -> lsu.slots.size,
            "physicalMacGenericsSimulated" -> false, "physicalQualification" -> false)
    }
}
