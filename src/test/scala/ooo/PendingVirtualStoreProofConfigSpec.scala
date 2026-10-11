package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Constructor-only checks; behavioral qualification is the independent GSIM suite. */
class PendingVirtualStoreProofConfigSpec extends AnyFunSuite {
    private val options = Set("--selected", "--virtual-ram-load-precheck", "--canonical-virtual-store-overlap",
        "--rob-entries=16", "--physical-regs=48", "--lsu-entries=4", "--data-translation-entries=16",
        "--load-order-older-retire")
    private val off = FpgaNextConfig.fromOptions(options, defaultSelected = true)
    test("constructor reporter rejects unknown and valued optional booleans") {
        val published = Seq("--selected", "--data-translation-entries=16", "--registered-pmp-regions",
            "--experimental-trispeed-ethernet", "--experimental-jtag-bscan=2", "--dma-line-transfers",
            "--dma-line-entries=4", "--prefetch-candidate-cycles=16", "--virtual-ram-load-precheck",
            "--lsu-entries=4", "--physical-load-ingress-flow", "--ddr-write-collection-flow",
            "--line-transfer-dispatch-flow", "--line-read-channel", "--dtlb-write-read-reuse",
            "--translation-hit-flow", "--independent-demand-admission", "--split-prefetch-tracking",
            "--read-prefetch-dirty-retry", "--read-prefetch-demand-adoption", "--load-order-older-retire",
            "--fetch-previous-packet", "--prepared-store-lookahead", "--store-next-line-prefetch",
            "--store-prefetch-mru-insertion", "--posted-store-merge", "--posted-prefetch-coexistence",
            "--posted-prefetch-head-offer", "--canonical-virtual-store-overlap", "--published-pmp-changes")
        val combined = published ++ Seq("--frozen-store-proof-transport", "--pending-virtual-store-proof",
            "--pending-virtual-store-proof-slots=1", "--bound-head-store-overlap", "--pending-ready-store-bypass", "--read-prefetch-store-hold")
        for (legal <- Seq(published, combined)) {
            FpgaNextProfileOptions.validate(legal)
            val config = FpgaNextConfig.fromOptions(legal.toSet, defaultSelected = true)
            assert(config.productArity == 56 && config.coreParams.productArity == 149 && config.cache.productArity == 19)
            assert(config.robEntries.isEmpty && config.physicalRegs.isEmpty)
            assert(config.coreParams.robEntries == 16 && config.coreParams.physicalRegs == 48)
        }
        for (flag <- Seq("--frozen-store-proof-transport", "--pending-virtual-store-proof",
            "--bound-head-store-overlap", "--pending-ready-store-bypass", "--read-prefetch-store-hold"); value <- Seq("true", "false", "0", "1")) {
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(Seq(flag + "=" + value)) }
            intercept[IllegalArgumentException] {
                FpgaNextConfig.fromOptions(Set(flag + "=" + value), defaultSelected = true)
            }
        }
        for (options <- Seq(Seq("--unknown"), Seq("--selected", "--selected"),
            Seq("--pending-virtual-store-proof-slots=3"), Seq("--reference", "--candidate"))) {
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(options) }
        }
        FpgaNextProfileOptions.validate(FpgaNextProfileOptions.allowed.toSeq.filterNot(_ == "--reference"))
    }

    test("proof bank and transport default off without changing the published profile") {
        assert(!off.pendingReadyStoreBypass && !off.boundHeadStoreOverlap && !off.pendingVirtualStoreProof && !off.frozenStoreProofTransport && off.pendingVirtualStoreProofSlots == 1)
        assert(!off.coreParams.frozenStoreProofEnabled && !FpgaNextConfig.Selected.pendingReadyStoreBypass && !FpgaNextConfig.Selected.boundHeadStoreOverlap && !FpgaNextConfig.Selected.pendingVirtualStoreProof)
        for (slots <- Seq(1, 2)) {
            val on = FpgaNextConfig.fromOptions(options ++ Set("--frozen-store-proof-transport",
                "--pending-virtual-store-proof", s"--pending-virtual-store-proof-slots=$slots"), defaultSelected = true)
            assert(on.coreParams.pendingVirtualStoreProof && on.coreParams.frozenStoreProofEnabled)
            assert(on.coreParams.pendingVirtualStoreProofSlots == slots && !on.coreParams.memoryProofFrontier)
            assert(on.copy(pendingVirtualStoreProof = false, frozenStoreProofTransport = false,
                pendingVirtualStoreProofSlots = 1) == off)
            assert(on.coreParams.copy(pendingVirtualStoreProof = false, frozenStoreProofTransport = false,
                pendingVirtualStoreProofSlots = 1) == off.coreParams)
            assert(on.cache == off.cache && on.ddr == off.ddr && on.storage == off.storage)
        }
    }
    test("omitted capacity overrides retain the published board profile metadata") {
        val original = FpgaNextConfig.fromOptions(options -- Set("--rob-entries=16", "--physical-regs=48"),
            defaultSelected = true)
        val on = original.copy(frozenStoreProofTransport = true, pendingVirtualStoreProof = true)
        assert(on.robEntries.isEmpty && on.physicalRegs.isEmpty)
        assert(on.coreParams.robEntries == 16 && on.coreParams.physicalRegs == 48)
        assert(on.copy(frozenStoreProofTransport = false, pendingVirtualStoreProof = false) == original)
    }
    test("transport is separately selectable and has no proof-bank scheduling authority") {
        val transport = off.copy(frozenStoreProofTransport = true)
        assert(transport.coreParams.frozenStoreProofEnabled && !transport.coreParams.pendingReadyStoreBypass && !transport.coreParams.boundHeadStoreOverlap && !transport.coreParams.pendingVirtualStoreProof)
        assert(!transport.coreParams.memoryProofFrontier)
    }
    test("bound head-store overlap is one default-off change on either pending-proof bank size") {
        for (slots <- Seq(1, 2)) {
            val proof = FpgaNextConfig.fromOptions(options ++ Set("--frozen-store-proof-transport",
                "--pending-virtual-store-proof", s"--pending-virtual-store-proof-slots=$slots"), defaultSelected = true)
            val overlap = FpgaNextConfig.fromOptions(options ++ Set("--frozen-store-proof-transport",
                "--pending-virtual-store-proof", s"--pending-virtual-store-proof-slots=$slots",
                "--bound-head-store-overlap"), defaultSelected = true)
            assert(!proof.pendingReadyStoreBypass && !proof.boundHeadStoreOverlap && !proof.coreParams.pendingReadyStoreBypass && !proof.coreParams.boundHeadStoreOverlap)
            assert(overlap.boundHeadStoreOverlap && overlap.coreParams.boundHeadStoreOverlap)
            assert(overlap.copy(boundHeadStoreOverlap = false) == proof)
            assert(overlap.coreParams.copy(boundHeadStoreOverlap = false) == proof.coreParams)
            assert(overlap.cache == proof.cache && overlap.ddr == proof.ddr && overlap.storage == proof.storage)
            assert(overlap.coreParams.productArity == 149 && overlap.productArity == 56)
        }
        intercept[IllegalArgumentException] { off.copy(boundHeadStoreOverlap = true) }
        intercept[IllegalArgumentException] { off.coreParams.copy(boundHeadStoreOverlap = true) }
        val on = off.copy(frozenStoreProofTransport = true, pendingVirtualStoreProof = true,
            boundHeadStoreOverlap = true)
        intercept[IllegalArgumentException] { on.copy(pendingVirtualStoreProof = false) }
        intercept[IllegalArgumentException] { on.coreParams.copy(pendingVirtualStoreProof = false) }
    }
    test("ready-store bypass is one default-off policy and requires bound head overlap") {
        assert(!OooParams().pendingReadyStoreBypass && !FpgaNextConfig.Selected.pendingReadyStoreBypass)
        for (slots <- Seq(1, 2)) {
            val baseOptions = options ++ Set("--frozen-store-proof-transport", "--pending-virtual-store-proof",
                s"--pending-virtual-store-proof-slots=$slots", "--bound-head-store-overlap")
            val base = FpgaNextConfig.fromOptions(baseOptions, defaultSelected = true)
            val on = FpgaNextConfig.fromOptions(baseOptions + "--pending-ready-store-bypass", defaultSelected = true)
            assert(!base.pendingReadyStoreBypass && !base.coreParams.pendingReadyStoreBypass)
            assert(on.pendingReadyStoreBypass && on.coreParams.pendingReadyStoreBypass)
            assert(on.copy(pendingReadyStoreBypass = false) == base)
            assert(on.coreParams.copy(pendingReadyStoreBypass = false) == base.coreParams)
            assert(on.cache == base.cache && on.ddr == base.ddr && on.storage == base.storage)
            assert(on.coreParams.copy(registeredIssueHeadMask = false).pendingReadyStoreBypass)
            intercept[IllegalArgumentException] { on.copy(boundHeadStoreOverlap = false) }
            intercept[IllegalArgumentException] { on.coreParams.copy(boundHeadStoreOverlap = false) }
            intercept[IllegalArgumentException] {
                FpgaNextConfig.fromOptions(baseOptions - "--bound-head-store-overlap" +
                    "--pending-ready-store-bypass", defaultSelected = true)
            }
        }
        intercept[IllegalArgumentException] { off.copy(pendingReadyStoreBypass = true) }
        intercept[IllegalArgumentException] { off.coreParams.copy(pendingReadyStoreBypass = true) }
        intercept[IllegalArgumentException] {
            FpgaNextProfileOptions.validate(Seq("--pending-ready-store-bypass", "--pending-ready-store-bypass"))
        }
    }
    test("capacity staging and original frontier qualification fail closed") {
        val on = off.copy(frozenStoreProofTransport = true, pendingVirtualStoreProof = true)
        for (slots <- Seq(0, 3)) {
            intercept[IllegalArgumentException] { on.copy(pendingVirtualStoreProofSlots = slots) }
        }
        intercept[IllegalArgumentException] { on.copy(frozenStoreProofTransport = false) }
        intercept[IllegalArgumentException] { on.copy(robEntries = Some(64)) }
        intercept[IllegalArgumentException] { on.copy(physicalRegs = Some(64)) }
        intercept[IllegalArgumentException] { on.copy(dataTranslationEntries = 8) }
        intercept[IllegalArgumentException] { on.copy(memoryProofFrontier = true) }
        intercept[IllegalArgumentException] { off.copy(memoryProofFrontier = true) }
        intercept[IllegalArgumentException] { on.coreParams.copy(registeredMemoryRequests = false) }
        intercept[IllegalArgumentException] { on.coreParams.copy(registeredLoadReplay = false) }
        intercept[IllegalArgumentException] { on.coreParams.copy(loadOrderOlderRetire = false) }
        intercept[IllegalArgumentException] { on.coreParams.copy(precheckedDataRequestFlow = true) }
    }
}
