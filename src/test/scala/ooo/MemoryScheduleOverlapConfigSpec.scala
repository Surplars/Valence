package ooo

import org.scalatest.freespec.AnyFreeSpec
import soc.core.ooo._

class MemoryScheduleOverlapConfigSpec extends AnyFreeSpec {
    "batch ownership overlap is opt-in and preserves all bounded resources" in {
        val off = FpgaNextConfig.Selected.copy(virtualRamLoadPrecheck = true,
            canonicalVirtualStoreOverlap = true, independentDemandAdmission = true)
        val on = off.copy(memoryScheduleOverlap = true)
        assert(!off.memoryScheduleOverlap && !off.cache.memoryScheduleOverlap)
        assert(on.cache == off.cache.copy(memoryScheduleOverlap = true))
        assert(on.coreParams == off.coreParams && on.storage == off.storage && on.ddr == off.ddr)
        assert(on.coreParams.issueWidth == 2)
        assert(on.cache.readMshrs == 2 && on.cache.responseEntries == 2 && on.cache.writebackEntries == 2)
        assert(on.productArity == 61 && on.cache.productArity == 22)
        val parsed = FpgaNextConfig.fromOptions(Set("--selected", "--virtual-ram-load-precheck",
            "--canonical-virtual-store-overlap", "--independent-demand-admission", "--memory-schedule-overlap"), false)
        assert(parsed.memoryScheduleOverlap && parsed.cache.memoryScheduleOverlap)
    }
    "missing independent authorization or unreviewed geometry is rejected" in {
        intercept[IllegalArgumentException] { FpgaNextConfig.Selected.copy(memoryScheduleOverlap = true) }
        intercept[IllegalArgumentException] { CoherentCacheConcurrency(memoryScheduleOverlap = true) }
        intercept[IllegalArgumentException] { CoherentCacheConcurrency(readMshrs = 4, responseEntries = 4,
            writebackEntries = 2, overlapWritebackRefill = true, independentDemandAdmission = true,
            memoryScheduleOverlap = true) }
        intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(Set("--memory-schedule-overlap=1"), false) }
    }
}
