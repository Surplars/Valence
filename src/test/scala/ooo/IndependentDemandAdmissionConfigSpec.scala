package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.{CoherentCacheConcurrency, FpgaNextConfig}

class IndependentDemandAdmissionConfigSpec extends AnyFunSuite {
    test("independent admission defaults OFF and changes no core, storage or capacities") {
        val off = FpgaNextConfig.Selected.copy(virtualRamLoadPrecheck = true, canonicalVirtualStoreOverlap = true)
        val on = off.copy(independentDemandAdmission = true)
        assert(off.productArity == 48 && !off.publishedPmpChanges && !off.registeredPmpRegions && !off.coreParams.registeredPmpRegions &&
                !off.readPrefetchDemandAdoption && !off.cache.readPrefetchDemandAdoption &&
            !off.readPrefetchDirtyRetry && !off.cache.readPrefetchDirtyRetry &&
            !off.splitPrefetchTracking && !off.cache.splitPrefetchTracking &&
            !off.independentDemandAdmission && !off.cache.independentDemandAdmission)
        assert(on.coreParams == off.coreParams && on.storage == off.storage && on.ddr == off.ddr)
        assert(on.cache.copy(independentDemandAdmission = false) == off.cache)
        assert(on.cache.readMshrs == 2 && on.cache.responseEntries == 2 && on.cache.writebackEntries == 2)
        assert(on.lsuEntries == 2 && on.instructionCacheLines == 512 && on.dataCacheLines == 512)
        assert(FpgaNextConfig.fromOptions(Set("--selected", "--virtual-ram-load-precheck",
            "--canonical-virtual-store-overlap", "--independent-demand-admission"), defaultSelected = false) == on)
    }
    test("reject absent store authority, single-MSHR topology and assigned boolean") {
        intercept[IllegalArgumentException] { FpgaNextConfig.Selected.copy(independentDemandAdmission = true) }
        intercept[IllegalArgumentException] {
            FpgaNextConfig.Selected.copy(virtualRamLoadPrecheck = true, independentDemandAdmission = true)
        }
        intercept[IllegalArgumentException] { CoherentCacheConcurrency(independentDemandAdmission = true) }
        intercept[IllegalArgumentException] {
            FpgaNextConfig.fromOptions(Set("--independent-demand-admission=false"), defaultSelected = false)
        }
    }
}
