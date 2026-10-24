package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.platform._

class CommonA1RuntimeSpec extends AnyFunSuite {
    test("production A1 runtime is still rejected without explicit complete candidate admission") {
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new CommonMachinePlatform(CommonCpuProfile.A1Boot50,
                independentDebugClock = true, runtimeDebugAdmission = true))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new CommonMachinePlatform(CommonCpuProfile.A1Boot50,
                experimentalA1Runtime = true))
        }
    }
    test("default static A1 keeps its original tile interface and no park state") {
        val fir = ChiselStage.emitCHIRRTL(new CommonA1CpuTile())
        val top = fir.substring(fir.indexOf("module CommonA1CpuTile :"))
        assert(!top.contains("runtimeHeld"))
        assert(!fir.contains("module CommonA1RuntimePark"))
        // The optional admission port does not exist in any default CPU wrapper.
        assert(!fir.contains("quiesce : UInt<1>"))
    }
}
object CommonA1StaticTileMain extends App {
    ChiselStage.emitSystemVerilogFile(new CommonA1CpuTile(), Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
