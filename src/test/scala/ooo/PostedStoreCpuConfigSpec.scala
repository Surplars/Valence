package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Source-only until the unified cache/CPU freeze is granted a heavy slot. */
class PostedStoreCpuConfigSpec extends AnyFunSuite {
    private val flags = Set("--selected", "--virtual-ram-load-precheck", "--data-translation-entries=16",
        "--prepared-store-lookahead", "--store-next-line-prefetch", "--store-prefetch-mru-insertion",
        "--lsu-entries=4", "--physical-load-ingress-flow", "--load-order-older-retire", "--fetch-previous-packet")
    test("posted selection preserves all existing architectural and cache dimensions") {
        val off = FpgaNextConfig.fromOptions(flags, defaultSelected = true)
        val on = FpgaNextConfig.fromOptions(flags + "--posted-store-merge", defaultSelected = true)
        assert(!OooParams().postedStoreMerge && !off.postedStoreMerge && off.coreParams.postedProofConfig.isEmpty)
        assert(on.copy(postedStoreMerge = false) == off)
        assert(on.coreParams.copy(postedStoreMerge = false) == off.coreParams)
        assert(on.cache == off.cache && on.ddr == off.ddr)
        assert(on.coreParams.memoryEntries == 4 && on.coreParams.physicalLoadIngressFlow &&
            on.coreParams.loadOrderOlderRetire && on.coreParams.fetchPreviousPacket)
        val shape = on.coreParams.postedProofConfig.get
        assert(!shape.enabled && shape.tokenTagBits == on.coreParams.tagBits &&
            shape.tokenIndexBits == on.coreParams.robBits && shape.epochBits == 32 && shape.generationBits == 64)
        intercept[IllegalArgumentException](OooParams(postedStoreMerge = true))
        intercept[IllegalArgumentException](on.coreParams.copy(bufferedRamStores = false))
        intercept[IllegalArgumentException](on.copy(precheckedDataRequestFlow = true))
    }
    test("the actual GSIM board builder elaborates posted owner and full proof only when selected") {
        def module(fir: String, name: String): String = {
            val pattern = ("(?ms)^  (?:public )?module " + name +
                "\\s*:.*?(?=^  (?:public )?(?:module|extmodule) |\\z)").r
            pattern.findFirstIn(fir).getOrElse(fail(s"missing emitted $name"))
        }
        for (enabled <- Seq(false, true)) {
            val config = FpgaNextConfig.fromOptions(flags ++ (if (enabled) Set("--posted-store-merge") else Set.empty), true)
            // Exactly the production CLI builder, not a second independently wired constructor.
            val fir = ChiselStage.emitCHIRRTL(FpgaNextBoardGsim.build(config))
            sys.env.get("POSTED_CPU_CENSUS_DIR").foreach { directory =>
                val path = java.nio.file.Paths.get(directory, if (enabled) "board-on.fir" else "board-off.fir")
                java.nio.file.Files.createDirectories(path.getParent)
                java.nio.file.Files.writeString(path, fir, java.nio.file.StandardOpenOption.CREATE_NEW)
            }
            val backend = module(fir, "IntegerBackend")
            val cache = module(fir, "NonBlockingCoherentLineCache")
            val stores = module(fir, "StoreBuffer")
            def io(body: String): String = body.linesIterator.find(_.startsWith("    output io :"))
                .getOrElse(fail("missing actual IO declaration"))
            assert(io(backend).contains("posted :") == enabled)
            assert(io(cache).contains("posted :") == enabled)
            assert(io(stores).contains("upstreamProof :") == enabled)
            assert(fir.contains("module PostedStoreMerge :") == enabled)
            assert(cache.contains("valid : UInt<1>[512]") && cache.contains("replacement : UInt<1>[256]"))
            assert(cache.contains("responseOwned : UInt<1>[2]") && cache.contains("wbLive : UInt<1>[2]"))
            if (enabled) {
                val owner = module(fir, "PostedStoreMerge")
                assert(owner.contains("index : UInt<4>, tag : UInt<64>"))
                assert(owner.contains("generation : UInt<64>") && owner.contains("epoch : UInt<32>"))
                assert(owner.contains("set : UInt<8>") && owner.contains("responseTicket : UInt<1>"))
                assert(backend.contains("headAuthorized") && cache.contains("finalChecked"))
                assert(stores.contains("proofs :") && cache.contains("postedContext :"))
            } else {
                assert(!backend.contains("requestProof :") && !cache.contains("postedContext :") && !stores.contains("proofs :"))
            }
        }
    }
}
