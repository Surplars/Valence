package ooo
import _root_.circt.stage.ChiselStage
import soc.core.ooo._
object PostedOwnerOffGsimMain extends App {
    require(args.length == 1)
    val c = PostedStoreMergeConfig(enabled = true, cacheSets = 8,
        guaranteedBase = 4096, guaranteedBytes = 4096)
    ChiselStage.emitCHIRRTLFile(new PostedStoreMerge(c), Array("--target-dir", args(0)))
}
