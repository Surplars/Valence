package ooo
import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._
class PreparationDescriptorGsim extends Module {
    val selector = Module(new MemoryPreparationDescriptorSelector(CombinedTimingR1Profile.config(true).coreParams))
    val io = IO(chiselTypeOf(selector.io))
    io <> selector.io
}
object PreparationDescriptorGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new PreparationDescriptorGsim, Array("--target-dir", args(0)))
}

class PreparationSourceLifetimeGsim extends Module {
    val check = Module(new PreparationSourceLifetimeCheck)
    val io = IO(chiselTypeOf(check.io))
    io <> check.io
}
object PreparationSourceLifetimeGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new PreparationSourceLifetimeGsim, Array("--target-dir", args(0)))
}
