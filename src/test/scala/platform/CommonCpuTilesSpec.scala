package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.platform._

class CommonCpuTilesSpec extends AnyFunSuite {
    test("I1 common profile preserves full batch44 CPU features with explicit AIA and TLB16") {
        val expected = inorder.I1IndependentClockProfile.fullCpu("src/main/resources/inorder/bootrom.hex").core
        val selected = CommonCpuProfile.I1.i1
        assert(selected.copy(resetVector = expected.resetVector, trapVector = expected.trapVector,
            tlbEntries = expected.tlbEntries, bankedTlbProofs = false,
            withAia = false, externalFenceICompletion = false) == expected)
        assert(selected.instructionCacheBytes == 32768 && selected.dataCacheBytes == 32768)
        assert(selected.withAia && selected.externalFenceICompletion && selected.tlbEntries == 16)
    }
    test("A1 tile contains private CPU and caches without duplicate platform peripherals") {
        val rtl = ChiselStage.emitCHIRRTL(new CommonA1CpuTile())
        assert(rtl.contains("module CommonA1CpuTile"))
        assert(rtl.contains("module Imsic"))
        assert(!rtl.contains("module Aplic"))
        assert(!rtl.contains("module CommonInterruptFabric"))
        assert(!rtl.contains("module InstructionRom"))
        assert(!rtl.contains("module MixedCoherentLineHome"))
    }
    test("I1 tile contains full coherent CPU AIA and acknowledged cache maintenance") {
        val rtl = ChiselStage.emitCHIRRTL(new CommonI1CpuTile())
        assert(rtl.contains("module FiveStageCore"))
        assert(rtl.contains("module Imsic"))
        assert(rtl.contains("invalidateDataDone"))
        assert(!rtl.contains("module FiveStagePlic"))
        assert(!rtl.contains("module InstructionRom"))
    }
    test("common asynchronous boundary elaborates all independent line and owner channels") {
        val rtl = ChiselStage.emitCHIRRTL(new CommonCpuClockBoundary())
        assert(rtl.contains("HeldResponseCdcDataFifo"))
        assert(rtl.contains("cpuEmptyInFabric"))
        assert(rtl.contains("fabricDrainedEpoch"))
    }
    test("both actual CPU choices instantiate one common full peripheral platform") {
        for (profile <- Seq(CommonCpuProfile.I1, CommonCpuProfile.A1)) {
            val rtl = ChiselStage.emitCHIRRTL(new CommonMachinePlatform(profile, hardwareClocks = false))
            assert(rtl.contains("module CommonMachineFabric"))
            assert(rtl.contains("module ManagedPeripheralBank"))
            assert(rtl.contains("module TriSpeedManagedGmac"))
            assert(rtl.contains("module JtagRamLoader"))
            assert(rtl.contains("module CommonCpuClockBoundary"))
            assert(rtl.contains(if (profile.kind == "i1") "module CommonI1CpuTile" else "module CommonA1CpuTile"))
            assert(!rtl.contains(if (profile.kind == "i1") "module CommonA1CpuTile" else "module CommonI1CpuTile"))
        }
    }
    test("shared timebase and existing seven-resource metadata do not follow CPU rate") {
        val profiles = Seq(CommonCpuProfile.I1, CommonCpuProfile.A1)
        profiles.foreach { p =>
            assert(p.cmu.resources.size == 7 && p.cmu.gateableMask == 0x68)
            assert(p.cmu.resources(1).nominalHz == p.cpuHz)
            assert(p.cmu.resources(2).nominalHz == 250000000 && p.cmu.resources(2).parent == -1)
            assert(p.clocks.legacyFirmwareCpuHz == 250000000)
        }
    }
}
