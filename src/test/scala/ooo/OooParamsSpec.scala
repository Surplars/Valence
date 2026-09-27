package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class OooParamsSpec extends AnyFunSuite {
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
