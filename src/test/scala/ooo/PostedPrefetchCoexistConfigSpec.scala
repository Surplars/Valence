package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.TLParams
import soc.core.ooo._

/** Configuration/elaboration only; dynamic edge witnesses use the separately bound GSIM top. */
class PostedPrefetchCoexistConfigSpec extends AnyFunSuite {
    private val flags = Set("--selected", "--posted-store-merge", "--virtual-ram-load-precheck",
        "--data-translation-entries=16", "--prepared-store-lookahead", "--store-next-line-prefetch",
        "--store-prefetch-mru-insertion", "--lsu-entries=4", "--physical-load-ingress-flow",
        "--load-order-older-retire", "--fetch-previous-packet")

    test("coexistence is default off and preserves authorization, geometry and capacities") {
        assert(!CoherentCacheConcurrency().postedPrefetchCoexistence)
        assert(!FpgaNextConfig().postedPrefetchCoexistence)
        for (config <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected)) {
            assert(!config.postedPrefetchCoexistence && !config.cache.postedPrefetchCoexistence)
        }
        val off = FpgaNextConfig.fromOptions(flags, defaultSelected = true)
        val on = FpgaNextConfig.fromOptions(flags + "--posted-prefetch-coexistence", defaultSelected = true)
        assert(on.copy(postedPrefetchCoexistence = false) == off)
        assert(on.cache.copy(postedPrefetchCoexistence = false) == off.cache)
        assert(on.coreParams == off.coreParams && on.ddr == off.ddr && on.network == off.network)
        assert(on.cache.readMshrs == 2 && on.cache.responseEntries == 2 && on.cache.writebackEntries == 2)
        assert(on.coreParams.issueWidth == 2 && on.coreParams.postedProofConfig == off.coreParams.postedProofConfig)
        assert(on.name == off.name + "-posted-prefetch-coexistence")
        // Read-only PF remains a legal coexistence policy; no store-PF authority is invented.
        val readOnly = FpgaNextConfig(postedStoreMerge = true, postedPrefetchCoexistence = true)
        assert(readOnly.cache.nextLinePrefetch && !readOnly.cache.storeNextLinePrefetch)
        assert(readOnly.coreParams.dataNextLinePrefetch && !readOnly.coreParams.dataStoreNextLinePrefetch)
    }

    test("unrelated and unqualified selector combinations fail before hardware generation") {
        intercept[IllegalArgumentException] { FpgaNextConfig(postedPrefetchCoexistence = true) }
        intercept[IllegalArgumentException] {
            FpgaNextConfig.fromOptions(Set("--posted-prefetch-coexistence"), defaultSelected = true)
        }
        intercept[IllegalArgumentException] {
            FpgaNextConfig.fromOptions(flags ++ Set("--posted-prefetch-coexistence", "--prechecked-data-flow"), true)
        }
        intercept[IllegalArgumentException] { CoherentCacheConcurrency(postedPrefetchCoexistence = true) }
        intercept[IllegalArgumentException] { CoherentCacheConcurrency(2, postedPrefetchCoexistence = true) }
        intercept[IllegalArgumentException] {
            CoherentCacheConcurrency(4, 4, nextLinePrefetch = true, postedPrefetchCoexistence = true)
        }
        val cfg = CoherentCacheConcurrency(2, nextLinePrefetch = true, postedPrefetchCoexistence = true)
        val tl = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = cfg.sourceBits, sinkBits = cfg.sinkBits)
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new NonBlockingCoherentLineCache(4096, 4096, 16, tl, 2, cfg))
        }
    }

    test("policy elaborates with exact existing posted resources and optional checked store PF") {
        for (enabled <- Seq(false, true); stores <- Seq(false, true); wb <- Seq(1, 2)) {
            val cfg = CoherentCacheConcurrency(2, 2, wb, overlapWritebackRefill = wb > 1,
                nextLinePrefetch = true, storeNextLinePrefetch = stores, postedPrefetchCoexistence = enabled)
            val c = PostedStoreMergeConfig(enabled = true, tokenTagBits = 64, tokenIndexBits = 4,
                cacheSets = 8, cacheWays = 2, writebackEntries = wb, guaranteedBase = 4096, guaranteedBytes = 4096)
            val tl = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = cfg.sourceBits, sinkBits = cfg.sinkBits)
            val fir = ChiselStage.emitCHIRRTL(new NonBlockingCoherentLineCache(4096, 4096, 16, tl, 2,
                cfg, CacheTagConfig(compact = true, bankedStorage = true), Some(c)))
            assert(fir.contains("module PostedStoreMerge"))
            assert(fir.contains("responseOwned : UInt<1>[2]") && fir.contains("phase : UInt<3>[2]"))
            assert(fir.contains("fallbackDrainActive") && fir.contains("generation : UInt<64>"))
            assert(fir.contains("prefetch crossed posted work") == enabled)
        }
    }
}
