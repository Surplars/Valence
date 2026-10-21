package inorder

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.inorder._
import soc.platform._

class I1ExternalQuiesceSpec extends AnyFunSuite {
    test("architectural quiesce is opt-in and is not a complete fabric drain endpoint") {
        val p = FiveStageConfig(pipelineProfile = "fpga8", fpgaTimingCuts = true)
        val ordinary = ChiselStage.emitCHIRRTL(new FiveStageCore(p))
        assert(!ordinary.contains("quiesceRequest") && !ordinary.contains("architecturalStopped"))
        val enabled = ChiselStage.emitCHIRRTL(new FiveStageCore(p, externalQuiesce = true))
        assert(enabled.contains("quiesceRequest") && enabled.contains("architecturalStopped"))
        assert(enabled.contains("external quiesce request withdrawn before architectural stop"))
        val tile = ChiselStage.emitCHIRRTL(new CommonI1CpuTile(externalQuiesce = true))
        assert(tile.contains("architecturalStopped") && tile.contains("CommonNativeOwnerAdapter"))
        assert(tile.contains("Coherent"))
    }
}
