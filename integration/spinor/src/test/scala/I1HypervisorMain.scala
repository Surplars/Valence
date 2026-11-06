package spinor_integration

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.core.inorder._
import soc.integration.spinor.I1SpinorManagedSystem

object I1HypervisorProfile {
    def core: FiveStageConfig = I1SpinorManagedProfile.core.copy(
        withUser = true, withSupervisor = true, withSv39 = true, withH = true)
}
class I1HypervisorStateFixture extends Module {
    val state = Module(new FiveStageMachineState(I1HypervisorProfile.core))
    val io = IO(chiselTypeOf(state.io))
    io <> state.io
}
object I1HypervisorStateMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1HypervisorStateFixture, Array("--target-dir", args.head))
}
object I1HypervisorSystemMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1SpinorManagedSystem(I1HypervisorProfile.core),
        Array("--target-dir", args.head))
}
