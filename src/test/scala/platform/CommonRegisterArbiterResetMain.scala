package platform

import _root_.circt.stage.ChiselStage
import soc.ip.bus.TwoMasterRegisterArbiter

/** Four-state cold-start regression: compare the preserved legacy constructor
  * with the explicitly reset-defined arbiter used at the shared MSI boundary.
  */
object CommonRegisterArbiterResetMain extends App {
    require(args.length == 2 && Set("legacy", "common").contains(args(1)))
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    ChiselStage.emitSystemVerilogFile(new TwoMasterRegisterArbiter(lockRequests = true,
        resetRoundRobin = args(1) == "common"), Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
