package spinor_integration

import _root_.circt.stage.ChiselStage
import soc.core.inorder.FiveStageConfig
import soc.integration.spinor.{I1SpinorManagedSystem, I1SpinorManagedFpga}

object I1SpinorManagedProfile {
    def core: FiveStageConfig = FiveStageConfig(withA = true, withC = true, withF = true, withD = true,
        multiplyMode = "dsp-tiled", pipelineProfile = "fpga8", fpgaTimingCuts = true,
        instructionCacheBytes = 32768, dataCacheBytes = 32768, branchPredictorEntries = 128,
        cacheFetchPredecode = true,
        hartId = 0xbeef, spinor = true)
}

object I1SpinorManagedMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1SpinorManagedSystem(I1SpinorManagedProfile.core),
        Array("--target-dir", args.head))
}

object I1SpinorManagedRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(new I1SpinorManagedFpga(I1SpinorManagedProfile.core),
        Array("--target-dir", args.head), Array("--split-verilog", "--lower-memories",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays"))
}
