package spinor_integration

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.integration.spinor._

class I1PsDdrFixture extends Module {
    val window = Module(new I1PsDdrWindow)
    val io = IO(chiselTypeOf(window.io)); io <> window.io
    val start = IO(Input(Bool())); val ddrReady = IO(Input(Bool()))
    val started = IO(Output(Bool())); val heldReset = IO(Output(Bool())); val memoryReady = IO(Output(Bool()))
    val boot = Module(new I1PsBootRelease)
    boot.systemClock := clock; boot.boardColdReset := reset.asAsyncReset
    boot.io.start := start; boot.io.ddrReady := ddrReady
    started := boot.io.started; heldReset := boot.io.subsystemColdReset.asBool
    memoryReady := boot.io.memoryReady
}
object I1PsDdrMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1PsDdrFixture, Array("--target-dir", args.head))
}
object I1PsFpgaMain extends App {
    ChiselStage.emitSystemVerilogFile(new I1SpinorPsFpga(I1HypervisorProfile.core),
        Array("--target-dir", args.head), firtoolOpts = Array("--disable-all-randomization", "--disable-layers=Verification"))
}
