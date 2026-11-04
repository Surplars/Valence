package inorder

import _root_.circt.stage.ChiselStage
import soc.core.inorder.I1HypervisorDecode

object I1HypervisorDecodeMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1HypervisorDecode(args(1).toInt), Array("--target-dir", args.head))
}
