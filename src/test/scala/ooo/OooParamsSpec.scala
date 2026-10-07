package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class OooParamsSpec extends AnyFunSuite {
    test("load issue forwarding is opt-in and preserves the registered two-issue board profile") {
        val baseline = BoardSocConfig.timingParams("staged-fetch-feedback")
        val candidate = BoardSocConfig.timingParams("staged-load-issue")
        assert(!baseline.registeredLoadIssueForwarding && !OooParams().registeredLoadIssueForwarding)
        assert(candidate.registeredLoadIssueForwarding && candidate.registeredIssueExecute)
        assert(!candidate.loadCompletionBypass && candidate.issueWidth == 2)
        assert(candidate.copy(registeredLoadIssueForwarding = false) == baseline)
        intercept[IllegalArgumentException] { OooParams(registeredLoadIssueForwarding = true) }
        intercept[IllegalArgumentException] { candidate.copy(loadCompletionBypass = true) }
        val board = BoardSocConfig.boardParams("staged-load-issue", externalDdr = true,
            isa = "rv64gc", ddrMemoryBytes = BigInt(1) << 31)
        assert(board.fpConfig.complete && board.speculativeRamBytes == (BigInt(1) << 31))
    }

    test("F/D configuration: RV64GC board profile matches discovery and rejects pruned extensions") {
        val off = BoardSocConfig.boardParams("staged-throughput", externalDdr = true)
        val f = BoardSocConfig.boardParams("staged-throughput", isa = "rv64imafc")
        val gc = BoardSocConfig.boardParams("staged-throughput", externalDdr = true, isa = "rv64gc")
        assert(off.advertisedIsa == "rv64imac_zicsr_zifencei" && !off.fpEnabled)
        assert(f.advertisedIsa == "rv64imafc_zicsr_zifencei" && !f.fpConfig.d)
        assert(gc.advertisedIsa == "rv64imafdc_zicsr_zifencei" && gc.fpConfig.complete && gc.fpConfig.d)
        assert(gc.atomicMemory && gc.compressedInstructions && gc.machineSystem && gc.issueWidth == 2)
        assert(gc.speculativeRamBytes == BoardSocConfig.ddrBytes && gc.virtualMemoryLevels == 3)
        assert((off.misaValue & 0x28) == 0 && (f.misaValue & 0x28) == 0x20 && (gc.misaValue & 0x28) == 0x28)
        assert(gc.misaValue == BigInt("800000000014112d", 16))
        intercept[IllegalArgumentException] { off.copy(advertiseFloatingPoint = true) }
        intercept[IllegalArgumentException] { gc.copy(floatingPoint = gc.fpConfig.copy(divide = false)) }
        intercept[IllegalArgumentException] { BoardSocConfig.boardParams("staged-throughput", isa = "rva23") }
        assert(!gc.copy(advertiseFloatingPoint = false).advertisedIsa.contains("f" + "d"))
    }
    test("F/D configuration is independent, defaults off and structurally prunes units") {
        assert(!OooParams().fpEnabled)
        assert(!BoardSocConfig.timingParams(BoardSocConfig.timingProfile).fpEnabled)
        intercept[IllegalArgumentException] { FloatingPointConfig(d = true) }
        intercept[IllegalArgumentException] { OooParams(floatingPoint = FloatingPointConfig.fullF) }
        val off = OooParams(machineSystem = true, robEntries = 8, physicalRegs = 40)
        val f = off.copy(floatingPoint = FloatingPointConfig.fullF)
        val fd = off.copy(floatingPoint = FloatingPointConfig.fullFD)
        assert(f.fpEnabled && !f.fpConfig.d && f.fpConfig.complete)
        assert(fd.fpEnabled && fd.fpConfig.d && fd.fpConfig.complete)
        assert(f.issueWidth == 2 && fd.issueWidth == 2)
        assert(off.copy(experimentalFloatingPoint = true).fpConfig == FloatingPointConfig.fullFD)
        val offRtl = ChiselStage.emitCHIRRTL(new MachineCore(off))
        assert(!offRtl.contains("module FloatingPoint"))
        val minimal = FloatingPointConfig.fullF.copy(addSubtract = false, multiply = false,
            divide = false, squareRoot = false, fusedMultiplyAdd = false,
            compareMinMax = false, conversions = false, memory = false)
        val minimalRtl = ChiselStage.emitCHIRRTL(new FloatingPointSystem(off.copy(floatingPoint = minimal)))
        assert(!minimal.complete)
        assert(!minimalRtl.contains("module LoadStoreUnit") && !minimalRtl.contains("module PmpChecker"))
        assert(!minimalRtl.contains("module FloatingPointArithmetic") &&
            !minimalRtl.contains("module FloatingPointDivSqrt") && !minimalRtl.contains("module INToRecFN"))
    }
    test("physical response owner cut requires the nonzero-latency TileLink translation boundary") {
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new MachinePlatform(registerPhysicalResponseOwners = true))
        }
        val rtl = ChiselStage.emitCHIRRTL(new SharedDataArbiter(registerResponseOwners = true))
        assert(rtl.contains("module SharedDataArbiter") && rtl.contains("module Queue8_Bool"))
    }

    test("registered board replay is opt-in and preserves the two-wide storage baseline") {
        val baseline = BoardSocConfig.timingParams(BoardSocConfig.timingProfile)
        val staged = BoardSocConfig.timingParams("registered-replay")
        assert(!baseline.registeredLoadReplay && !baseline.registeredRobRetirement)
        assert(staged.registeredLoadReplay && staged.registeredRobRetirement)
        assert(staged.registeredMemoryAddress && staged.earlyRecoveryIssueBlock)
        assert(staged.renameWidth == 2 && staged.commitWidth == 2 && staged.issueWidth == 2)
        assert(staged.copy(registeredLoadReplay = false, registeredRobRetirement = false) == baseline)
    }

    test("compact board four-wide candidate changes widths without growing storage capacities") {
        val baseline = BoardSocConfig.timingParams("early-issue")
        val wide = BoardSocConfig.timingParams("early-issue", 4)
        assert(baseline.renameWidth == 2 && baseline.issueWidth == 2 && baseline.commitWidth == 2)
        assert(wide.renameWidth == 4 && wide.issueWidth == 4 && wide.commitWidth == 4)
        assert(wide.copy(renameWidth = 2, completionWidth = 2, commitWidth = 2) == baseline)
        assert(wide.robEntries == 16 && wide.physicalRegs == 48 && wide.frontendCacheSets == 16)
        assert(wide.memoryEntries == 2 && wide.storeBufferEntries == 2)
        intercept[IllegalArgumentException] { BoardSocConfig.timingParams("early-issue", 3) }
    }

    test("frontend cache defaults to 128 sets for four-wide cores and remains overrideable") {
        assert(OooParams().frontendCacheSets == 64)
        assert(OooParams(renameWidth = 4).frontendCacheSets == 128)
        assert(OooParams(renameWidth = 4, instructionCacheSets = 64).frontendCacheSets == 64)
    }

    test("atomic execution requires an explicit reservation-aligned RAM window") {
        intercept[IllegalArgumentException] { OooParams(atomicMemory = true) }
        intercept[IllegalArgumentException] {
            OooParams(atomicMemory = true, speculativeRamBase = 8, speculativeRamBytes = 64)
        }
        intercept[IllegalArgumentException] { OooParams(atomicMemory = true, speculativeRamBytes = 65) }
        assert(OooParams(atomicMemory = true, speculativeRamBytes = 64).atomicMemory)
    }

    test("machine platform keeps synchronous storage and omits the simulation programming port by default") {
        val rtl = ChiselStage.emitCHIRRTL(new MachinePlatform())
        assert(rtl.contains("module SynchronousFetch") && rtl.contains("module SynchronousDataRam"))
        assert(rtl.contains("module AtomicDataMemory") && rtl.contains("module AtomicMemory"))
        assert(rtl.contains("module MappedMachineCore") && rtl.contains("module UartConsole"))
        assert(rtl.contains("uartRx") && rtl.contains("uartTx") && !rtl.contains("program :"))
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new MachinePlatform(romWords = 3)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new MachinePlatform(OooParams())) }
    }

    test("machine assembly exposes separate MSI/CSR boundaries and enables system execution") {
        val rtl = ChiselStage.emitCHIRRTL(new MachineCore(OooParams(robEntries = 8, physicalRegs = 36)))
        assert(rtl.contains("module MachineSystemUnit") && rtl.contains("module Imsic"))
        val baseline = ChiselStage.emitCHIRRTL(new IntegerCore())
        assert(!baseline.contains("module MachineSystemUnit"))
    }
    test("elaborate synchronous byte-write RAM and reject invalid address windows") {
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new SynchronousDataRam(12)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new SynchronousDataRam(base = 3)) }
        assert(ChiselStage.emitCHIRRTL(new SynchronousDataRam()).contains("smem"))
    }
    test("elaborate synchronous FPGA instruction boundary and reject invalid ROM geometry") {
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new InstructionRom(3, 0)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new InstructionRom(256, 4)) }
        assert(ChiselStage.emitCHIRRTL(new FpgaIntegerCore()).contains("module SynchronousFetch"))
        assert(ChiselStage.emitCHIRRTL(new InstructionRom(256, 0)).contains("smem"))
    }
    test("reject configurations with invalid hardware index widths or insufficient capacity") {
        for (
            make <- Seq[() => OooParams](
                () => OooParams(renameWidth = 0),
                () => OooParams(commitWidth = 7),
                () => OooParams(completionWidth = 0),
                () => OooParams(renameWidth = 1, commitWidth = 1, robEntries = 1),
                () => OooParams(renameWidth = 6, robEntries = 4),
                () => OooParams(commitWidth = 6, robEntries = 4),
                () => OooParams(robEntries = 12),
                () => OooParams(physicalRegs = 32),
                () => OooParams(physicalRegs = 257),
                () => OooParams(tagBits = 7),
                () => OooParams(tagBits = 65),
                () => OooParams(memoryEntries = 0),
                () => OooParams(memoryEntries = 3),
                () => OooParams(memoryEntries = 16),
                () => OooParams(storeBufferEntries = 0),
                () => OooParams(storeBufferEntries = 3),
                () => OooParams(bufferedRamStores = true),
                () => OooParams(registeredLocalStoreResponses = true),
                () => OooParams(registeredMemoryRequests = true),
                () => OooParams(registeredStoreResponseOwners = true),
                () => OooParams(registeredLoadReplay = true),
                () => OooParams(bufferedRamStores = true, speculativeRamBytes = 4096,
                    registeredMemoryAddress = true, fastBufferedStoreRetire = true),
                () => OooParams(earlyRecoveryIssueBlock = true),
                () => OooParams(precompleteMispredictedBranch = true),
                () => OooParams(fastBufferedStoreRetire = true),
                () => OooParams(branchPredictorEntries = 0),
                () => OooParams(branchPredictorEntries = 3),
                () => OooParams(branchPredictorEntries = 512),
                () => OooParams(speculativeRamBase = -1),
                () => OooParams(speculativeRamBytes = -1),
                () => OooParams(speculativeRamBase = (BigInt(1) << 64) - 4, speculativeRamBytes = 8)
            )
        ) {
            intercept[IllegalArgumentException] { make() }
        }
    }

    test("elaborate boundary capacities and wider ledger interfaces without zero-width indices") {
        for (
            p <- Seq(
                OooParams(renameWidth = 1, commitWidth = 1, completionWidth = 1, robEntries = 2, physicalRegs = 33),
                OooParams(renameWidth = 4, commitWidth = 2, completionWidth = 3, robEntries = 8, physicalRegs = 40),
                OooParams(renameWidth = 6, commitWidth = 4, completionWidth = 6, robEntries = 8, physicalRegs = 40)
            )
        ) {
            val firrtl = ChiselStage.emitCHIRRTL(new RenameRob(p))
            assert(firrtl.contains("module RenameRob"))
            assert(!firrtl.contains("UInt<0>"))
        }
    }

    test("elaborate integer backend with independent allocation execution and commit widths") {
        for (
            p <- Seq(
                OooParams(renameWidth = 1, commitWidth = 1, completionWidth = 1, robEntries = 2, physicalRegs = 33),
                OooParams(renameWidth = 4, commitWidth = 2, completionWidth = 3, robEntries = 8, physicalRegs = 40),
                OooParams(renameWidth = 6, commitWidth = 4, completionWidth = 6, robEntries = 8, physicalRegs = 40)
            )
        ) {
            val firrtl = ChiselStage.emitCHIRRTL(new IntegerBackend(p))
            assert(firrtl.contains("module IntegerBackend"))
            assert(!firrtl.contains("UInt<0>"))
        }
    }

    test("elaborate all memory slot capacities") {
        for (slots <- Seq(1, 2, 4, 8)) {
            val firrtl = ChiselStage.emitCHIRRTL(new ParallelLoadStoreUnit(OooParams(memoryEntries = slots)))
            assert(firrtl.contains("module ParallelLoadStoreUnit"))
        }
    }

    test("elaborate guaranteed RAM store buffer capacities") {
        for (entries <- Seq(1, 2, 4, 8)) {
            val p = OooParams(bufferedRamStores = true, speculativeRamBytes = 4096, storeBufferEntries = entries)
            assert(ChiselStage.emitCHIRRTL(new StoreBuffer(p)).contains("module StoreBuffer"))
        }
    }

    test("elaborate branch predictor table sizes with wide lookup and retirement") {
        for (entries <- Seq(2, 64, 256)) {
            val p = OooParams(renameWidth = 6, commitWidth = 6, branchPredictorEntries = entries)
            assert(ChiselStage.emitCHIRRTL(new BranchPredictor(p)).contains("module BranchPredictor"))
        }
    }

    test("coherent cache and bounded home support matched one or two way capacities") {
        for (ways <- Seq(1, 2)) {
            val cache = ChiselStage.emitCHIRRTL(new CoherentLineCache(lines = 4, ways = ways))
            val home = ChiselStage.emitCHIRRTL(new CoherentLineHome(
                bytes = 8192, trackedLines = 4, trackedWays = ways))
            assert(cache.contains("module CoherentLineCache") && !cache.contains("UInt<0>"))
            assert(home.contains("module CoherentLineHome") && !home.contains("UInt<0>"))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new CoherentLineCache(lines = 4, ways = 3))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new CoherentLineHome(trackedLines = 2, trackedWays = 2))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new CoherentLineHome(nClients = 2, trackedLines = 4, trackedWays = 2))
        }
    }

    test("integer fetch runner enforces aligned reset addresses and elaborates mixed widths") {
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new IntegerCore(resetPc = 2))
        }
        for (width <- Seq(1, 2, 4, 6)) {
            val p      = OooParams(renameWidth = width, commitWidth = 2, completionWidth = 2)
            val firrtl = ChiselStage.emitCHIRRTL(new IntegerCore(p))
            assert(firrtl.contains("module IntegerCore"))
            assert(!firrtl.contains("UInt<0>"))
        }
    }
}
