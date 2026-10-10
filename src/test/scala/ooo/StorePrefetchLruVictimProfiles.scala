package ooo

import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** The already reviewed ROB64/PRF64/frontier profile, with one independent cache policy flag. */
object StorePrefetchLruVictimProfiles {
    // Exact key/value set from the same frozen actual-parameter JSON pinned by
    // MemoryProofFrontierExactFixture.originalModelSha256; no omitted defaults.
    private val originalCacheFields = Map(
        "readMshrs" -> "2", "responseEntries" -> "2", "writebackEntries" -> "2",
        "overlapWritebackRefill" -> "true", "nextLinePrefetch" -> "true",
        "prefetchCandidateCycles" -> "1", "prefetchBreakOnStore" -> "false",
        "storeNextLinePrefetch" -> "true", "storePrefetchMruInsertion" -> "true",
        "postedPrefetchCoexistence" -> "true")
    def options(enabled: Boolean): Set[String] = MemoryProofFrontierExactFixture.canonicalOptions ++
        Set("--memory-proof-frontier") ++
        (if (enabled) Set("--store-prefetch-lru-victim") else Set.empty[String])

    def profile(enabled: Boolean): FpgaNextConfig = {
        val original = MemoryProofFrontierExactFixture.profile(true)
        val selected = FpgaNextConfig.fromOptions(options(enabled), defaultSelected = false)
        require(selected == original.copy(storePrefetchLruVictim = enabled))
        require(selected.productArity == 31 && selected.coreParams.productArity == 139)
        require(selected.coreParams == original.coreParams)
        MemoryProofFrontierExactFixture.validate(selected.coreParams)
        val expectedCache = CoherentCacheConcurrency(readMshrs = 2, responseEntries = 2,
            writebackEntries = 2, overlapWritebackRefill = true, nextLinePrefetch = true,
            prefetchCandidateCycles = 1, prefetchBreakOnStore = false, storeNextLinePrefetch = true,
            storePrefetchMruInsertion = true, postedPrefetchCoexistence = true,
            storePrefetchLruVictim = enabled)
        require(selected.cache.productArity == 11 && selected.cache == expectedCache)
        val actualCacheFields = selected.cache.productElementNames.zip(selected.cache.productIterator)
            .map { case (name, value) => name -> value.toString }.toMap
        require(actualCacheFields.keySet == originalCacheFields.keySet + "storePrefetchLruVictim",
            "actual cache constructor field set differs from frozen original plus policy")
        originalCacheFields.foreach { case (name, value) =>
            require(actualCacheFields(name) == value, s"original cache field changed: $name")
        }
        require(actualCacheFields("storePrefetchLruVictim") == enabled.toString)
        require(selected.cache.copy(storePrefetchLruVictim = false) == original.cache)
        require(selected.ddr == original.ddr && selected.tags == original.tags && selected.storage == original.storage &&
            selected.network == original.network && selected.floatingPointResources == original.floatingPointResources)
        selected
    }

    def arguments(args: Array[String]): Boolean = {
        require(args.length == 2 && Set("off", "on").contains(args(1)),
            "fresh-output-directory and explicit off|on required")
        require(!Files.exists(Paths.get(args(0))), "store PF victim audit requires a fresh directory")
        args(1) == "on"
    }
}

/** Pure full-constructor report. It does not elaborate hardware. */
object StorePrefetchLruVictimProfileMain extends App {
    val enabled = StorePrefetchLruVictimProfiles.arguments(args)
    PostedBoardConfiguration.write(StorePrefetchLruVictimProfiles.profile(enabled), args(0))
}

/** One actual native construction; the audit reads all six core, three cache and two DDR parameter records. */
object StorePrefetchLruVictimNativeMain extends App {
    val enabled = StorePrefetchLruVictimProfiles.arguments(args)
    val profile = StorePrefetchLruVictimProfiles.profile(enabled)
    PostedBoardConfiguration.write(profile, args(0))
    // The reused audit's mode names canonical overlap, which stays ON on both sides.
    new CanonicalVirtualStoreActualParamsAudit(profile, args(0), "on",
        StorePrefetchLruVictimProfiles.options(enabled), "store-prefetch-lru-victim-" + args(1))
}
