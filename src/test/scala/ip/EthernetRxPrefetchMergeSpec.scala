package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.dma.{EthernetPacketDma, NetworkDmaConfig}
import soc.ip.ethernet.GmiiFrameRx

/** Configuration/elaboration coverage for prefetch plus the newer DMA options. */
class EthernetRxPrefetchMergeSpec extends AnyFunSuite {
    test("prefetch remains opt-in with independent validated export switches") {
        assert(!NetworkDmaConfig.Default.rxWritePrefetch)
        assert(!NetworkDmaConfig.Default.macRxReadPrefetch)
        for (dma <- Seq(0, 1); mac <- Seq(0, 1)) {
            val (args, config) = NetworkDmaConfig.parseArgs(Array("out",
                s"--network-rx-write-prefetch=$dma", s"--network-mac-rx-read-prefetch=$mac"))
            assert(args.toSeq == Seq("out"))
            assert(config.rxWritePrefetch == (dma == 1))
            assert(config.macRxReadPrefetch == (mac == 1))
        }
        for (key <- Seq("network-rx-write-prefetch", "network-mac-rx-read-prefetch")) {
            for (bad <- Seq(-1, 2)) {
                intercept[IllegalArgumentException](NetworkDmaConfig.parseArgs(Array(s"--$key=$bad")))
            }
            intercept[IllegalArgumentException](NetworkDmaConfig.parseArgs(Array(s"--$key=0", s"--$key=1")))
        }
    }

    test("DMA prefetch composes with bounded descriptors and runtime ownership") {
        for (prefetch <- Seq(false, true); bounded <- Seq(false, true); runtime <- Seq(false, true)) {
            val rtl = ChiselStage.emitCHIRRTL(new EthernetPacketDma(ramBytes = 8192,
                postedTxSlots = 4, boundedDescriptorChecks = bounded, runtimeAdmission = runtime,
                rxWritePrefetch = prefetch))
            assert(rtl.contains("module EthernetTxDescriptorQueue"))
            assert(rtl.contains("runtimeOwnersIdle") == runtime)
            assert(rtl.contains("memoryOfferHeld") == runtime)
            assert(rtl.contains("regreset offerHeld") == prefetch)
            assert(rtl.contains("regreset readPending") == prefetch)
        }
    }

    test("MAC prefetch composes with single and multiple banks and runtime diagnostics") {
        for (prefetch <- Seq(false, true); slots <- Seq(1, 4)) {
            val rtl = ChiselStage.emitCHIRRTL(new GmiiFrameRx(frameSlots = slots,
                admissionStop = true, rateAdaptation = true, diagnostics = true, readPrefetch = prefetch))
            assert(rtl.contains(s"smem buffer : UInt<32>[${slots * 512}]"))
            assert(rtl.contains("regreset readsDone") == prefetch)
        }
    }
}
