package inorder

import _root_.circt.stage.ChiselStage
import soc.core.inorder.I1CoherentDeviceFrontEnd

object I1DeviceFrontEndMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1CoherentDeviceFrontEnd(args.contains("--cuts"), args.contains("--compact")),
        Array("--target-dir", args.head))
}
