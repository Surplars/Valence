package spinor_integration

import chisel3._
import _root_.circt.stage.ChiselStage
import vpu.VectorMemoryEngine

/** Native LSU completion hold/admission boundary, with no CPU or memory oracle. */
class I1VpuMemoryReplyFixture extends Module {
    val unit = Module(new VectorMemoryEngine(shortUnitAdder = true, pipelineDecode = true))
    val io = IO(chiselTypeOf(unit.io))
    io <> unit.io
}
object I1VpuMemoryReplyMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1VpuMemoryReplyFixture, Array("--target-dir", args.head))
}
