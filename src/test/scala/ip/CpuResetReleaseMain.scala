package ip
import chisel3._
import _root_.circt.stage.ChiselStage
import soc.ip.bus.{CdcResetRelease, ResetDistributionDriver}

/** Compare both supported release structures against a software edge counter. */
class CpuResetReleaseHarness extends RawModule {
    val rawClock = IO(Input(Clock()))
    val coldReset = IO(Input(AsyncReset()))
    val conventional = IO(Output(Bool()))
    val distributed = IO(Output(Bool()))
    val three = Module(new CdcResetRelease)
    three.clockIn := rawClock; three.asyncReset := coldReset
    conventional := three.resetOut.asBool
    val two = Module(new CdcResetRelease(syncStages = 2))
    two.clockIn := rawClock; two.asyncReset := coldReset
    val driver = Module(new ResetDistributionDriver)
    driver.clockIn := rawClock; driver.synchronizedReset := two.resetOut
    distributed := driver.resetOut.asBool
}
object CpuResetReleaseMain extends App {
    ChiselStage.emitCHIRRTLFile(new CpuResetReleaseHarness, Array("--target-dir", args.head))
}
