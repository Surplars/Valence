package ooo

import org.scalatest.freespec.AnyFreeSpec
import soc.core.ooo._

class LineGrantPrefetchConfigSpec extends AnyFreeSpec {
    "private full Grant and dual-origin PF preserve capacities and default OFF" in {
        val off = FpgaNextConfig.Selected
        assert(off.productArity == 61 && off.cache.productArity == 22 && off.coreParams.productArity == 151)
        assert(!off.internalLineGrant && !off.concurrentReadStorePrefetch && !off.memoryScheduleOverlap)
        assert(!off.cache.internalLineGrant && !off.cache.concurrentReadStorePrefetch)
        val durable = off.copy(virtualRamLoadPrecheck = true, canonicalVirtualStoreOverlap = true,
            independentDemandAdmission = true, prefetchCandidateCycles = 16, storeNextLinePrefetch = true,
            splitPrefetchTracking = true, readPrefetchDirtyRetry = true, readPrefetchDemandAdoption = true,
            readPrefetchStoreHold = true, durableReadPrefetchCandidate = true, readPrefetchBehindStore = true)
        val on = durable.copy(internalLineGrant = true, concurrentReadStorePrefetch = true)
        assert(on.cache == durable.cache.copy(internalLineGrant = true, concurrentReadStorePrefetch = true))
        assert(on.coreParams == durable.coreParams && on.ddr == durable.ddr && on.storage == durable.storage)
        assert(on.cache.readMshrs == 2 && on.cache.responseEntries == 2 && on.cache.writebackEntries == 2)
        assert(on.instructionCacheLines == off.instructionCacheLines && on.dataCacheLines == off.dataCacheLines)
        val parsed = FpgaNextConfig.fromOptions(Set("--selected", "--internal-line-grant"), false)
        assert(parsed.internalLineGrant && parsed.cache.internalLineGrant && !parsed.concurrentReadStorePrefetch)
    }
    "unreviewed owner geometry or missing qualified PF origins is rejected" in {
        intercept[IllegalArgumentException] { CoherentCacheConcurrency(internalLineGrant = true) }
        intercept[IllegalArgumentException] { FpgaNextConfig.Selected.copy(concurrentReadStorePrefetch = true) }
        intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(Set("--internal-line-grant=1"), false) }
        intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(Set("--concurrent-read-store-prefetch=0"), false) }
    }
}
