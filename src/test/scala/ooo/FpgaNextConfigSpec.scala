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

}
