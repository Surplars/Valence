package ooo

import org.scalatest.funsuite.AnyFunSuite
import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

/** Short affected gate only. Full hierarchy behavior remains a separate GSIM obligation. */
class TimingBatchConfigSpec extends AnyFunSuite {
    private val options = Set(
        "--selected",
        "--data-translation-entries=16",
        "--registered-pmp-regions",
        "--experimental-trispeed-ethernet",
        "--experimental-jtag-bscan=2",
        "--dma-line-transfers",
        "--dma-line-entries=4",
        "--prefetch-candidate-cycles=16",
        "--virtual-ram-load-precheck",
        "--lsu-entries=4",
        "--physical-load-ingress-flow",
        "--ddr-write-collection-flow",
        "--line-transfer-dispatch-flow",
        "--line-read-channel",
        "--dtlb-write-read-reuse",
        "--translation-hit-flow",
        "--independent-demand-admission",
        "--split-prefetch-tracking",
        "--read-prefetch-dirty-retry",
        "--read-prefetch-demand-adoption",
        "--load-order-older-retire",
        "--fetch-previous-packet",
        "--prepared-store-lookahead",
        "--store-next-line-prefetch",
        "--store-prefetch-mru-insertion",
        "--posted-store-merge",
        "--posted-prefetch-coexistence",
        "--posted-prefetch-head-offer",
        "--canonical-virtual-store-overlap",
        "--published-pmp-changes",
        "--frozen-store-proof-transport",
        "--pending-virtual-store-proof",
        "--pending-virtual-store-proof-slots=2",
        "--bound-head-store-overlap",
        "--read-prefetch-store-hold",
        "--pending-ready-store-bypass",
        "--durable-read-prefetch-candidate",
        "--read-prefetch-behind-store",
        "--pending-store-early-load-credits=2",
        "--tagged-store-returns",
        "--internal-line-grant",
        "--concurrent-read-store-prefetch",
        "--memory-schedule-overlap")
    private val off = FpgaNextConfig.fromOptions(options, defaultSelected = true)
    test("explicit A+C and A+B+C preserve every existing maxperf constructor field") {
        assert(options.size == 43)
        assert(off.productArity == 65 && off.coreParams.productArity == 155 && off.cache.productArity == 22)
        for (generic <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected, off)) {
            assert(!generic.registeredPendingStoreQuery && !generic.alignedFetchPermissionStage &&
                !generic.registeredCanonicalStoreEvent)
        }
        assert(off.cpuHz == 100000000 && off.lsuEntries == 4 && off.dataTranslationEntries == 16 &&
            off.dmaLineEntries == 4 && off.pendingVirtualStoreProofSlots == 2 &&
            off.pendingStoreEarlyLoadCredits == 2 && off.taggedStoreReturns && off.experimentalTriSpeedEthernet)
        for (fetch <- Seq(false, true)) {
            val flags = Set("--registered-pending-store-query", "--registered-canonical-store-event") ++
                (if (fetch) Set("--aligned-fetch-permission-stage") else Set.empty[String])
            FpgaNextProfileOptions.validate((options ++ flags).toSeq)
            val on = FpgaNextConfig.fromOptions(options ++ flags, defaultSelected = true)
            assert(on.registeredPendingStoreQuery && on.registeredCanonicalStoreEvent &&
                on.alignedFetchPermissionStage == fetch)
            assert(on.copy(registeredPendingStoreQuery = false, registeredCanonicalStoreEvent = false,
                alignedFetchPermissionStage = false) == off)
            assert(on.coreParams.copy(registeredPendingStoreQuery = false, registeredCanonicalStoreEvent = false,
                alignedFetchPermissionStage = false) == off.coreParams)
            assert(on.cache == off.cache && on.ddr == off.ddr && on.storage == off.storage && on.network == off.network)
        }
    }
    test("all stage options reject duplicates values and absent prerequisites") {
        for (flag <- Seq("--registered-pending-store-query", "--registered-canonical-store-event",
            "--aligned-fetch-permission-stage")) {
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(Seq(flag, flag)) }
            for (value <- Seq("true", "false", "0", "1")) {
                intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(Seq(flag + "=" + value)) }
                intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(Set(flag + "=" + value), true) }
            }
        }
        intercept[IllegalArgumentException] { OooParams(registeredPendingStoreQuery = true) }
        intercept[IllegalArgumentException] { OooParams(registeredCanonicalStoreEvent = true) }
        intercept[IllegalArgumentException] { OooParams(alignedFetchPermissionStage = true) }
        intercept[IllegalArgumentException] { FpgaNextConfig(registeredCanonicalStoreEvent = true) }
    }
    test("actual module constructors reject either canonical endpoint mismatching its Ooo flag") {
        for (stage <- Seq(false, true)) {
            val p = off.coreParams.copy(registeredCanonicalStoreEvent = stage)
            val backendError = intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new IntegerBackend(p, registerCanonicalStoreEvent = !stage))
            }
            assert(backendError.getMessage.contains("same OooParams flag"))
            val adapterError = intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new DataTranslationAdapter(p, registerCheckedRequests = true,
                    registerCanonicalStoreEvent = !stage))
            }
            assert(adapterError.getMessage.contains("same OooParams flag"))
        }
    }
    test("actual query bank rejects stage loss or unexpected activation") {
        for (stage <- Seq(false, true)) {
            val error = intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new Module {
                    val io = IO(new Bundle {})
                    val p = off.coreParams.copy(registeredPendingStoreQuery = stage)
                    val bank = Module(new PendingVirtualStoreProof(p, registerQuery = !stage))
                    TimingBatchActualAudit.requireQueryStage(p.registeredPendingStoreQuery, Some(bank))
                })
            }
            assert(error.getMessage.contains("actual pending query stage differs"))
        }
    }
    test("actual fetch module mode mismatch is rejected by optional-port audit") {
        val error = intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new Module {
                val io = IO(new Bundle {})
                val packet = Module(new RegisteredFetchPacket(2, true, BigInt("80000000", 16),
                    parallelValidation = true, hintEntries = 32, splitCursor = true,
                    bankedHints = true, alignedPermissionStage = false))
                TimingBatchActualAudit.requireFetchPorts(true,
                    "packet phase input" -> packet.io.phaseInput.nonEmpty,
                    "packet frontier" -> packet.io.requestFrontier.nonEmpty,
                    "packet suppress" -> packet.io.suppressRequest.nonEmpty)
            })
        }
        assert(error.getMessage.contains("fetch phase optional port mismatch"))
    }
}
