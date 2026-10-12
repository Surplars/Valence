package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class ReadPrefetchStoreHoldConfigSpec extends AnyFunSuite {
    private val flag = "--read-prefetch-store-hold"

    test("store hold defaults OFF and changes only one cache policy with no new core fields") {
        assert(!CoherentCacheConcurrency().readPrefetchStoreHold)
        for (base <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected);
            cycles <- Seq(3, 16)) {
            assert(!base.readPrefetchStoreHold && !base.cache.readPrefetchStoreHold)
            val off = base.copy(prefetchCandidateCycles = cycles)
            val on = off.copy(readPrefetchStoreHold = true)
            assert(on.productArity == 57 && on.cache.productArity == 19 && on.coreParams.productArity == 150)
            assert(on.copy(readPrefetchStoreHold = false) == off)
            assert(on.cache.copy(readPrefetchStoreHold = false) == off.cache)
            assert(on.coreParams == off.coreParams && on.ddr == off.ddr && on.tags == off.tags)
            assert(on.storage == off.storage && on.network == off.network)
            assert(on.name == off.name + "-read-prefetch-store-hold")
        }
    }

    test("store hold requires next-line prefetch and an existing finite candidate lifetime") {
        intercept[IllegalArgumentException] { CoherentCacheConcurrency(readPrefetchStoreHold = true) }
        intercept[IllegalArgumentException] {
            CoherentCacheConcurrency(2, nextLinePrefetch = true, readPrefetchStoreHold = true)
        }
        val on = CoherentCacheConcurrency(2, nextLinePrefetch = true,
            prefetchCandidateCycles = 16, readPrefetchStoreHold = true)
        intercept[IllegalArgumentException] { on.copy(nextLinePrefetch = false) }
        intercept[IllegalArgumentException] { on.copy(prefetchCandidateCycles = 1) }
        intercept[IllegalArgumentException] { FpgaNextConfig(readPrefetchStoreHold = true) }
        for (cycles <- Seq(2, 3, 16, 32)) assert(on.copy(prefetchCandidateCycles = cycles).readPrefetchStoreHold)
    }

    test("native option forwarding and boolean validation preserve unrelated policies") {
        for (selector <- Seq("--reference", "--candidate", "--selected"); cycles <- Seq(3, 16)) {
            val options = Set(selector, s"--prefetch-candidate-cycles=$cycles")
            val off = FpgaNextConfig.fromOptions(options, defaultSelected = false)
            val on = FpgaNextConfig.fromOptions(options + flag, defaultSelected = false)
            assert(on == off.copy(readPrefetchStoreHold = true))
            assert(on.cache == off.cache.copy(readPrefetchStoreHold = true) && on.coreParams == off.coreParams)
        }
        intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(Set(flag), defaultSelected = true) }
        for (value <- Seq("true", "false", "0", "1")) {
            intercept[IllegalArgumentException] {
                FpgaNextConfig.fromOptions(Set("--prefetch-candidate-cycles=16", s"$flag=$value"),
                    defaultSelected = true)
            }
        }
    }
}
