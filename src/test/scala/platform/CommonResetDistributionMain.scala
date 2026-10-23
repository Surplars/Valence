package platform

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.ip.bus.{CdcResetRelease, ResetDistributionDriver}

/** Real reset cells plus one retained-owner register; no behavioral reset model. */
class CommonResetDistributionFixture extends RawModule {
    val cpuClock = IO(Input(Clock()))
    val startupReset = IO(Input(AsyncReset()))
    val acquire = IO(Input(Bool()))
    val retire = IO(Input(Bool()))
    val synchronizedReset = IO(Output(Bool()))
    val functionalReset = IO(Output(Bool()))
    val owner = IO(Output(Bool()))
    private val release = Module(new CdcResetRelease)
    release.clockIn := cpuClock
    release.asyncReset := startupReset
    private val distribution = Module(new ResetDistributionDriver)
    distribution.clockIn := cpuClock
    distribution.asyncReset := startupReset
    distribution.synchronizedReset := release.resetOut
    synchronizedReset := release.resetOut.asBool
    functionalReset := distribution.resetOut.asBool
    owner := withClockAndReset(cpuClock, distribution.resetOut) {
        val held = RegInit(false.B)
        when(acquire) { held := true.B }
        when(retire) { held := false.B }
        held
    }
}

object CommonResetDistributionMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new CommonResetDistributionFixture,
        Array("--target-dir", args(0)), Array("--split-verilog", "--strip-debug-info",
            "--disable-all-randomization", "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
