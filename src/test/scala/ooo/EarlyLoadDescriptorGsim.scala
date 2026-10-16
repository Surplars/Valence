package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

class EarlyLoadDescriptorGsim extends Module {
    val selector = Module(new MemoryPreparationDescriptorSelector(
        CombinedTimingRepairR1Profile.config(true).coreParams, earlyLoads = true))
    val io = IO(chiselTypeOf(selector.io))
    io <> selector.io
}
object EarlyLoadDescriptorGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new EarlyLoadDescriptorGsim, Array("--target-dir", args(0)))
}
class EarlyLoadSourceLifetimeGsim extends Module {
    val check = Module(new PreparationSourceLifetimeCheck(allowPendingLoad = true))
    val io = IO(chiselTypeOf(check.io))
    io <> check.io
}
object EarlyLoadSourceLifetimeGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new EarlyLoadSourceLifetimeGsim, Array("--target-dir", args(0)))
}
