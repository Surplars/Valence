package platform

import _root_.circt.stage.ChiselStage
import soc.platform._

/** Explicit opt-in topology emission, not a board configuration or rate backend. */
object CommonRuntimeDebugPlatformMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new CommonMachinePlatform(CommonCpuProfile.I1Performance300,
        hardwareClocks = true, vivadoMemories = true, independentDdrClock = true,
        independentTimebaseClock = true, independentDebugClock = true, runtimeDebugAdmission = true),
        Array("--target-dir", args(0)), Array("--split-verilog", "--strip-debug-info",
            "--disable-all-randomization", "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
