package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class DurableReadPrefetchConfigSpec extends AnyFunSuite {
    private val retention = "--durable-read-prefetch-candidate"
    private val capture = "--read-prefetch-behind-store"
    private val prerequisites = Set("--prefetch-candidate-cycles=16", "--store-next-line-prefetch",
        "--split-prefetch-tracking", "--read-prefetch-dirty-retry", "--read-prefetch-demand-adoption",
        "--read-prefetch-store-hold", "--independent-demand-admission", "--virtual-ram-load-precheck",
        "--canonical-virtual-store-overlap")

    test("independent default-OFF READ policies preserve every CPU and capacity field") {
        assert(!CoherentCacheConcurrency().durableReadPrefetchCandidate &&
            !CoherentCacheConcurrency().readPrefetchBehindStore)
        for (selector <- Seq("--reference", "--candidate", "--selected")) {
            val off = FpgaNextConfig.fromOptions(prerequisites + selector, defaultSelected = false)
            val retained = FpgaNextConfig.fromOptions(prerequisites + selector + retention, defaultSelected = false)
            val captured = FpgaNextConfig.fromOptions(prerequisites + selector + retention + capture, defaultSelected = false)
            assert(off.productArity == 58 && !off.taggedStoreReturns && off.cache.productArity == 19 && off.coreParams.productArity == 151 && !off.coreParams.taggedStoreReturns)
            assert(!off.durableReadPrefetchCandidate && !off.readPrefetchBehindStore)
            assert(retained == off.copy(durableReadPrefetchCandidate = true))
            assert(captured == retained.copy(readPrefetchBehindStore = true))
            assert(captured.cache == off.cache.copy(durableReadPrefetchCandidate = true, readPrefetchBehindStore = true))
            assert(captured.coreParams == off.coreParams && captured.ddr == off.ddr && captured.tags == off.tags)
            assert(captured.storage == off.storage && captured.network == off.network)
            assert(retained.name == off.name + "-durable-read-prefetch-candidate")
            assert(captured.name == retained.name + "-read-prefetch-behind-store")
        }
        for (p <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected))
            assert(!p.durableReadPrefetchCandidate && !p.readPrefetchBehindStore)
    }

    test("new policies require the exact first-qualified cache profile and unvalued booleans") {
        for (missing <- prerequisites) {
            intercept[IllegalArgumentException] {
                FpgaNextConfig.fromOptions(prerequisites - missing + retention, defaultSelected = true)
            }
        }
        intercept[IllegalArgumentException] {
            FpgaNextConfig.fromOptions(prerequisites + capture, defaultSelected = true)
        }
        val c = FpgaNextConfig.fromOptions(prerequisites + retention, defaultSelected = true).cache
        for (n <- Seq(1, 3, 32)) intercept[IllegalArgumentException] { c.copy(prefetchCandidateCycles = n) }
        intercept[IllegalArgumentException] { c.copy(readMshrs = 4, responseEntries = 4) }
        intercept[IllegalArgumentException] { c.copy(writebackEntries = 4) }
        for (flag <- Seq(retention, capture); value <- Seq("true", "false", "0", "1")) {
            intercept[IllegalArgumentException] {
                FpgaNextConfig.fromOptions(prerequisites + retention + s"$flag=$value", defaultSelected = true)
            }
        }
        FpgaNextProfileOptions.validate((prerequisites + retention + capture).toSeq)
        intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(Seq(retention, retention)) }
    }
}
