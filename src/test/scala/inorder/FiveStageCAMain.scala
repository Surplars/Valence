package inorder

import _root_.circt.stage.ChiselStage
import soc.core.inorder._

object FiveStageCompressedMain extends App {
    ChiselStage.emitCHIRRTLFile(new FiveStageCompressed(args(1).toInt), Array("--target-dir", args.head))
}
object FiveStageFetchAlignerMain extends App {
    val cuts = args.contains("--timing-cuts")
    require(args.drop(2).forall(_ == "--timing-cuts"), "unknown parcel option")
    ChiselStage.emitCHIRRTLFile(new FiveStageFetchAligner(FiveStageConfig(xlen = args(1).toInt, withC = true,
        fpgaTimingCuts = cuts, pipelineProfile = if (cuts) "fpga8" else "compact5")), Array("--target-dir", args.head))
}
object FiveStageAtomicMain extends App {
    ChiselStage.emitCHIRRTLFile(new FiveStageAtomicMemory(FiveStageConfig(xlen = args(1).toInt, withA = true)),
        Array("--target-dir", args.head))
}
object FiveStageSocRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(new FiveStageSoc(FiveStageSocArguments.config(args)),
        Array("--target-dir", args.head),
        Array("--split-verilog", "--lowering-options=disallowLocalVariables,disallowPackedArrays"))
}
