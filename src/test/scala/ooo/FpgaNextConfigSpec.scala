package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class FpgaNextConfigSpec extends AnyFunSuite {
    test("FPGA-next geometry preserves the frozen full RV64GC release") {
        val c = FpgaNextConfig.Reference
        val p = c.coreParams
        assert(c.interfaceVersion == 1 && c.isaProfile == "rv64gc")
        assert(p.advertisedIsa == "rv64imafdc_zicsr_zifencei")
        assert(p.renameWidth == 2 && p.commitWidth == 2 && p.completionWidth == 2)
        assert(p.memoryEntries == 2 && p.robEntries == 16 && p.physicalRegs == 48)
        assert(p.fpEnabled && p.fpConfig.complete && p.atomicMemory && p.compressedInstructions)
        assert(p.pmpEntries == 16 && p.virtualMemoryLevels == 3)
        assert(c.cpuHz == 100000000 && c.uartBaud == 460800)
        assert(c.instructionCacheLines * c.cacheLineBytes == 32768)
        assert(c.dataCacheLines * c.cacheLineBytes == 32768 && c.cacheWays == 2)
    }
    test("candidate selects qualified replacements without changing the architectural dimensions") {
        val reference = FpgaNextConfig.Reference
        val candidate = FpgaNextConfig.Candidate
        assert(candidate.tags.bankedStorage && !reference.tags.bankedStorage)
        assert(candidate.floatingPointResources.committedStateMemory && candidate.floatingPointResources.sharedFormatRounders)
        assert(candidate.floatingPointResources.sharedMultiplyFused)
        assert(candidate.coreParams.fpConfig.resources == candidate.floatingPointResources)
        assert(candidate.coreParams.bankedIssuePayload && candidate.coreParams.bankedFetchHints)
        assert(candidate.coreParams.copy(floatingPoint = reference.coreParams.floatingPoint,
            bankedIssuePayload = false, bankedFetchHints = false) == reference.coreParams)
        assert(candidate.ddr == reference.ddr && candidate.cache == reference.cache && candidate.network == reference.network)
        assert(!candidate.virtualRamLoadPrecheck)
    }
    test("selected v2 assembles the qualified storage and control choices") {
        val c = FpgaNextConfig.Selected
        assert(c.selectedTopology && c.name == "fpga-next-selected-v2")
        assert(c.bankedInstructionData && c.storage.shareProtectedHeadPayload)
        assert(c.coreParams.shareProtectedHeadPayload)
        assert(c.coreParams.copy(shareProtectedHeadPayload = false) == FpgaNextConfig.ControlCandidate.coreParams)
        assert(FpgaNextConfig.fromOptions(Set.empty, defaultSelected = true) == c)
        assert(FpgaNextConfig.fromOptions(Set("--candidate"), defaultSelected = true) == FpgaNextConfig.Candidate)
        assert(FpgaNextConfig.fromOptions(Set("--reference"), defaultSelected = true) == FpgaNextConfig.Reference)
        intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(Set("--selected", "--reference"), true) }
    }
    test("retained prefetch experiments preserve geometry and stay explicit") {
        val base = FpgaNextConfig.Selected
        assert(base.prefetchCandidateCycles == 1 && base.cache.prefetchCandidateCycles == 1)
        for (attempts <- Seq(3, 16)) {
            val candidate = FpgaNextConfig.fromOptions(Set("--selected", s"--prefetch-candidate-cycles=$attempts"), true)
            assert(candidate.cache.copy(prefetchCandidateCycles = 1) == base.cache)
            assert(candidate.coreParams == base.coreParams && candidate.ddr == base.ddr)
            assert(candidate.prefetchCandidateCycles == attempts && candidate.name.endsWith(s"prefetch-retry$attempts"))
        }
        intercept[IllegalArgumentException] { FpgaNextConfig(prefetchCandidateCycles = 0) }
        intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(Set("--prefetch-candidate-cycles=3", "--prefetch-candidate-cycles=16"), true) }
    }
    test("accepted-store history policy is an independent default-off option") {
        val base = FpgaNextConfig.Selected.copy(prefetchCandidateCycles = 3)
        val c = FpgaNextConfig.fromOptions(Set("--selected", "--prefetch-candidate-cycles=3", "--prefetch-break-on-store"), true)
        assert(!base.prefetchBreakOnStore && c.prefetchBreakOnStore)
        assert(c.cache.copy(prefetchBreakOnStore = false) == base.cache)
        assert(c.coreParams == base.coreParams && c.ddr == base.ddr)
        assert(c.name.endsWith("prefetch-retry3-store-break"))
    }
    test("control candidate preserves capacity and independently exposes both cone changes") {
        val c = FpgaNextConfig.ControlCandidate
        val p = c.coreParams
        assert(p.ownerLocalIssueReady && p.sharedFetchPmpRelations && p.independentFetchPayloadCapture)
        assert(p.copy(ownerLocalIssueReady = false, sharedFetchPmpRelations = false,
            independentFetchPayloadCapture = false) == FpgaNextConfig.Candidate.coreParams)
        assert(!FpgaNextConfig.Candidate.ownerLocalIssueReady && !FpgaNextConfig.Candidate.sharedFetchPmpRelations)
    }
    test("tri-speed is an explicitly experimental peripheral option") {
        val c = FpgaNextConfig.TriSpeedCandidate
        assert(c.experimentalTriSpeedEthernet && !FpgaNextConfig.Candidate.experimentalTriSpeedEthernet)
        assert(c.coreParams == FpgaNextConfig.Candidate.coreParams)
        assert(c.name.contains("experimental-trispeed"))
        assert(c.triSpeedTxFrameSlots == 2 && FpgaNextConfig.Candidate.triSpeedTxFrameSlots == 1)
    }
    test("payload capture is an explicit timing variant with unchanged base geometry") {
        val base = FpgaNextConfig.Candidate
        val candidate = FpgaNextConfig.FetchCaptureCandidate
        assert(!base.coreParams.independentFetchPayloadCapture)
        assert(candidate.coreParams.independentFetchPayloadCapture)
        assert(candidate.coreParams.copy(independentFetchPayloadCapture = false) == base.coreParams)
        assert(candidate.name != base.name)
    }
    test("the DDR aperture is full-width and has independent shared/write limits") {
        val c = FpgaNextConfig.Reference
        assert(c.ramBase == BigInt("80200000", 16))
        assert(c.ddrBytes == BigInt(1) << 31)
        assert(c.ramEndExclusive == BigInt("100200000", 16))
        assert(c.ramEndExclusive > (BigInt(1) << 32))
        assert(c.ddr.maxOutstanding == 4 && c.ddr.maxOutstandingWrites == 2)
        assert(c.ddr.maxBurstBeats == 16 && c.ddr.axiIdWidth == 4 && c.ddr.unorderedResponses)
        c.ddr.validateSoc()
        assert(c.cache.readMshrs == 2 && c.cache.writebackEntries == 2 && c.cache.responseEntries == 2)
        assert(c.cache.overlapWritebackRefill && c.cache.nextLinePrefetch)
    }
    test("inherited storage options and protection cannot silently disappear") {
        val p = FpgaNextConfig.Reference.coreParams
        assert(p.bankedRobPayload && p.sharedStoreOperandReads && p.lvtPhysicalRegisterFile)
        assert(p.registeredLoadIssueForwarding && p.identityDataRequestFlow && p.dataNextLinePrefetch)
        assert(!p.virtualRamLoadPrecheck)
        assert(FpgaNextConfig(virtualRamLoadPrecheck = true).coreParams.virtualRamLoadPrecheck)
        assert(FpgaNextConfig(virtualRamLoadPrecheck = true).coreParams.copy(virtualRamLoadPrecheck = false) == p)
        assert(!BoardSocConfig.boardParams(BoardSocConfig.timingProfile).fpEnabled)
        assert(!BoardSocConfig.params.lvtPhysicalRegisterFile)
    }
    test("bounded DMA yield is explicit and does not change transaction credits") {
        for (cycles <- Seq(0, 4, 8, 16, 32, 64)) {
            val c = FpgaNextConfig.fromOptions(Set("--selected", "--dma-line-transfers",
                s"--dma-line-yield-cycles=$cycles"), true)
            assert(c.dmaLineTransfers && c.dmaLineYieldCycles == cycles)
            assert(c.ddr == FpgaNextConfig.Selected.ddr && c.cache == FpgaNextConfig.Selected.cache)
        }
        intercept[IllegalArgumentException] { FpgaNextConfig(dmaLineYieldCycles = 4) }
    }
    test("line DMA remains an explicit option without larger bridge or cache geometry") {
        val base = FpgaNextConfig.Selected
        val c = FpgaNextConfig.fromOptions(Set("--selected", "--dma-line-transfers"), true)
        assert(!base.dmaLineTransfers && c.dmaLineTransfers)
        assert(c.copy(dmaLineTransfers = false) == base)
        assert(c.coreParams == base.coreParams && c.ddr == base.ddr && c.cache == base.cache)
        assert(c.name == base.name + "-dma-lines")
    }

    test("tagged line depth is explicit and does not silently enlarge DDR slots") {
        for (depth <- Seq(2, 4)) {
            val c = FpgaNextConfig.fromOptions(Set("--selected", "--dma-line-transfers", s"--dma-line-entries=$depth"), true)
            assert(c.dmaLineEntries == depth && c.name.endsWith(s"-dma-lines-owners$depth"))
            assert(c.ddr == FpgaNextConfig.Selected.ddr && c.cache == FpgaNextConfig.Selected.cache)
        }
        intercept[IllegalArgumentException] { FpgaNextConfig(dmaLineEntries = 2) }
        intercept[IllegalArgumentException] { FpgaNextConfig(dmaLineTransfers = true, dmaLineEntries = 3) }
    }

    test("CPU flow and tagged DMA compose only through explicit independent options") {
        val baseline = FpgaNextConfig.Selected
        assert(!baseline.physicalLoadIngressFlow && !baseline.precheckedDataRequestFlow)
        assert(!baseline.dmaLineTransfers && baseline.dmaLineEntries == 1 && baseline.dmaLineYieldCycles == 0)
        val c = FpgaNextConfig.fromOptions(Set("--selected", "--physical-load-ingress-flow",
            "--dma-line-transfers", "--dma-line-entries=4"), true)
        assert(c.coreParams == baseline.coreParams.copy(physicalLoadIngressFlow = true))
        assert(c.dmaLineTransfers && c.dmaLineEntries == 4 && c.dmaLineYieldCycles == 0)
        assert(c.cache == baseline.cache && c.ddr == baseline.ddr && c.network == baseline.network)
        assert(c.name == "fpga-next-selected-v2-physical-ingress-flow-dma-lines-owners4")
        val checked = c.copy(virtualRamLoadPrecheck = true, precheckedDataRequestFlow = true)
        assert(checked.coreParams.virtualRamLoadPrecheck && checked.coreParams.precheckedDataRequestFlow)
        assert(checked.dmaLineEntries == c.dmaLineEntries && checked.ddr == c.ddr)
        intercept[IllegalArgumentException] { c.copy(precheckedDataRequestFlow = true) }
    }

    test("four LSU owners retain every other current selected parameter") {
        val base = FpgaNextConfig.Selected.copy(physicalLoadIngressFlow = true,
            dmaLineTransfers = true, dmaLineEntries = 4)
        val four = FpgaNextConfig.fromOptions(Set("--selected", "--physical-load-ingress-flow",
            "--dma-line-transfers", "--dma-line-entries=4", "--lsu-entries=4"), true)
        assert(FpgaNextConfig.Selected.lsuEntries == 2 && four.lsuEntries == 4)
        assert(four.coreParams.memoryEntries == 4)
        assert(four.coreParams.copy(memoryEntries = 2) == base.coreParams)
        assert(four.cache == base.cache && four.ddr == base.ddr && four.network == base.network)
        assert(four.storage == base.storage && four.floatingPointResources == base.floatingPointResources)
        assert(four.dataCacheLines == base.dataCacheLines && four.instructionCacheLines == base.instructionCacheLines)
        assert(four.name.contains("-lsu4") && four.timingProfile == BoardSocConfig.memoryCapacityProfile)
        intercept[IllegalArgumentException] { base.copy(lsuEntries = 3) }
        intercept[IllegalArgumentException] {
            FpgaNextConfig.fromOptions(Set("--selected", "--lsu-entries=2", "--lsu-entries=4"), true)
        }
    }

    test("older-load retirement changes only its explicit registered boundary option") {
        val options = Set("--selected", "--physical-load-ingress-flow", "--lsu-entries=4",
            "--dma-line-transfers", "--dma-line-entries=4")
        val off = FpgaNextConfig.fromOptions(options, true)
        val on = FpgaNextConfig.fromOptions(options + "--load-order-older-retire", true)
        assert(!off.loadOrderOlderRetire && !FpgaNextConfig.Selected.loadOrderOlderRetire)
        assert(on.loadOrderOlderRetire && on.coreParams.registeredLoadReplay)
        assert(on.coreParams.copy(loadOrderOlderRetire = false) == off.coreParams)
        assert(on.copy(loadOrderOlderRetire = false) == off)
        assert(on.cache == off.cache && on.ddr == off.ddr && on.storage == off.storage)
        assert(on.network == off.network && on.floatingPointResources == off.floatingPointResources)
        assert(!on.coreParams.virtualRamLoadPrecheck && !on.coreParams.precheckedDataRequestFlow)
        assert(on.name == off.name.replace("-lsu4", "-lsu4-older-load-retire"))
        intercept[IllegalArgumentException] { OooParams(loadOrderOlderRetire = true) }
    }

    test("previous fetch packet stays default-off and changes only its registered-window option") {
        for (profile <- Seq("--reference", "--candidate", "--selected")) {
            val base = FpgaNextConfig.fromOptions(Set(profile), defaultSelected = true)
            val enabled = FpgaNextConfig.fromOptions(Set(profile, "--fetch-previous-packet"), defaultSelected = true)
            assert(!base.fetchPreviousPacket && !base.coreParams.fetchPreviousPacket)
            assert(enabled.fetchPreviousPacket && enabled.coreParams.registeredFetchWindow)
            assert(enabled.coreParams.copy(fetchPreviousPacket = false) == base.coreParams)
            assert(enabled.copy(fetchPreviousPacket = false) == base)
            assert(enabled.name == base.name + "-fetch-previous-packet")
        }
        val options = Set("--selected", "--physical-load-ingress-flow", "--lsu-entries=4",
            "--dma-line-transfers", "--dma-line-entries=4", "--dma-line-yield-cycles=0")
        val off = FpgaNextConfig.fromOptions(options, defaultSelected = true)
        val on = FpgaNextConfig.fromOptions(options + "--fetch-previous-packet", defaultSelected = true)
        assert(on.copy(fetchPreviousPacket = false) == off)
        assert(on.coreParams.copy(fetchPreviousPacket = false) == off.coreParams)
        assert(on.coreParams.fetchPreviousPacket && on.coreParams.registeredFetchWindow)
        assert(on.lsuEntries == 4 && on.coreParams.memoryEntries == 4 && on.physicalLoadIngressFlow)
        assert(on.dmaLineTransfers && on.dmaLineEntries == 4 && on.dmaLineYieldCycles == 0)
        assert(!on.virtualRamLoadPrecheck && !on.precheckedDataRequestFlow && !on.loadOrderOlderRetire)
        assert(on.cache == off.cache && on.ddr == off.ddr && on.storage == off.storage)
        assert(on.network == off.network && on.floatingPointResources == off.floatingPointResources)
        assert(on.name == off.name.replace("-lsu4", "-lsu4-fetch-previous-packet"))
        val older = FpgaNextConfig.fromOptions(options + "--load-order-older-retire", defaultSelected = true)
        val both = FpgaNextConfig.fromOptions(options ++ Set("--load-order-older-retire", "--fetch-previous-packet"),
            defaultSelected = true)
        assert(both.copy(fetchPreviousPacket = false) == older)
        assert(both.coreParams.copy(fetchPreviousPacket = false) == older.coreParams)
    }

    test("previous fetch packet rejects configurations without the registered window") {
        assert(!OooParams().fetchPreviousPacket)
        intercept[IllegalArgumentException] { OooParams(fetchPreviousPacket = true) }
        intercept[IllegalArgumentException] {
            OooParams(compressedInstructions = true, registeredFetchPacket = true, fetchPreviousPacket = true)
        }
        intercept[IllegalArgumentException] {
            BoardSocConfig.boardParams("staged-ethernet", externalDdr = true, fetchPreviousPacket = true)
        }
        val p = BoardSocConfig.boardParams("staged-fetch-feedback", externalDdr = true, fetchPreviousPacket = true)
        assert(p.registeredFetchWindow && p.fetchPreviousPacket)
    }

}
