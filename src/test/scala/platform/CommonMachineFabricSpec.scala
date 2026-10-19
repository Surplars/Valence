package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.platform._

/** Focused elaboration verifies the actual shared fabric, not a source-string
  * substitute for its protocol behavior (covered by the separate GSIM driver).
  */
class CommonMachineFabricSpec extends AnyFunSuite {
    test("production fabric contains one shared Home and all existing enabled platform peripherals") {
        val firrtl = ChiselStage.emitCHIRRTL(new CommonMachineFabric(
            features = CommonPlatformFeatures(true, true, true, true)))
        assert(firrtl.contains("module CommonMachineFabric"))
        assert(firrtl.contains("module MixedCoherentLineHome"))
        assert(firrtl.contains("module CommonFabricScalarArbiter"))
        assert(firrtl.contains("module TileLinkAxi4OutstandingBridge"))
        assert(firrtl.contains("module CommonInterruptFabric"))
        assert(firrtl.contains("module EthernetPacketDma"))
        assert(firrtl.contains("module JtagRamLoader"))
        assert(firrtl.contains("module MemoryCopyDma"))
        assert(!firrtl.contains("module MachinePlatform"))
        assert(!firrtl.contains("module CommonA1CpuTile"))
        assert(!firrtl.contains("module I1Core"))
    }
    test("both profiles keep the same physical fabric capacities") {
        val selected = soc.core.ooo.FpgaNextConfig.Selected
        assert(selected.ddr.maxOutstanding == 4 && selected.ddr.maxOutstandingWrites == 2)
        assert(CommonCpuTilePortParams().coherentClients == 2)
        assert(CommonCpuTilePortParams().homeAcquireEntries == 2)
        assert(CommonCpuTilePortParams().homeWritebackEntries == 2)
        assert(CommonPlatformAbi.romWords == 32768)
    }
}
