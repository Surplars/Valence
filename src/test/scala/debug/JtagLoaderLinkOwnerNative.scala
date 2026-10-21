package debug

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.ip.bus.{CdcResetRelease, RegisterPort}
import soc.ip.debug.{DebugDmiClockBoundary, DebugDmiPort, JtagRamLoader}

/** Real loader + real DMI crossing. Link reset is deliberately NOT loader reset. */
class JtagLoaderLinkOwnerNative extends RawModule {
    val sourceClock = IO(Input(Clock()))
    val fabricClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val sourceLinkUp = IO(Input(Bool()))
    val destinationLinkUp = IO(Output(Bool()))
    val source = IO(Flipped(new DebugDmiPort(7)))
    val control = IO(Flipped(new RegisterPort))
    val memory = IO(new RegisterPort)
    val crossing = Module(new DebugDmiClockBoundary)
    crossing.sourceClock := sourceClock
    crossing.destinationClock := fabricClock
    crossing.commonColdReset := commonColdReset
    crossing.sourceLinkUp := sourceLinkUp
    source <> crossing.source
    destinationLinkUp := crossing.destinationLinkUp
    val release = Module(new CdcResetRelease)
    release.clockIn := fabricClock
    release.asyncReset := commonColdReset
    val loader = withClockAndReset(fabricClock, release.resetOut) {
        Module(new JtagRamLoader(BigInt("80200000", 16), BigInt("80210000", 16)))
    }
    loader.io.dmi <> crossing.destination
    loader.io.linkUp := crossing.destinationLinkUp
    loader.io.control <> control
    memory <> loader.io.memory
}
object JtagLoaderLinkOwnerNativeMain extends App {
    ChiselStage.emitSystemVerilogFile(new JtagLoaderLinkOwnerNative,
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable"))
}
