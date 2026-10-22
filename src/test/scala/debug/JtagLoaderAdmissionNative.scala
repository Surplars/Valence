package debug

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.bus.{CdcResetRelease, RegisterPort}
import soc.ip.debug.{DebugDmiAdmissionBoundary, DebugDmiPort, JtagRamLoader}

/** Real loader, DMI mailbox transport and opt-in admission protocol. Stalls
  * affect genuine request/response handshakes; no owner or payload is invented.
  */
class JtagLoaderAdmissionNative extends RawModule {
    val sourceClock = IO(Input(Clock()))
    val fabricClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val sourceLinkUp = IO(Input(Bool()))
    val destinationLinkUp = IO(Output(Bool()))
    val source = IO(Flipped(new DebugDmiPort(7)))
    val control = IO(Flipped(new RegisterPort))
    val memory = IO(new RegisterPort)
    val prepare = IO(Flipped(Decoupled(UInt(8.W))))
    val cancel = IO(Flipped(Decoupled(UInt(8.W))))
    val resume = IO(Flipped(Decoupled(UInt(8.W))))
    val held = IO(Valid(UInt(8.W)))
    val terminal = IO(Decoupled(new Bundle {
        val epoch = UInt(8.W)
        val canceled = Bool()
    }))
    val busy = IO(Output(Bool()))
    val fault = IO(Output(Bool()))
    val holdDestinationRequest = IO(Input(Bool()))
    val holdDestinationResponse = IO(Input(Bool()))
    val destinationRequestFire = IO(Output(Bool()))
    val destinationResponseFire = IO(Output(Bool()))
    val loaderOwnersIdle = IO(Output(Bool()))
    val boundary = Module(new DebugDmiAdmissionBoundary)
    boundary.sourceClock := sourceClock
    boundary.destinationClock := fabricClock
    boundary.commonColdReset := commonColdReset
    boundary.sourceLinkUp := sourceLinkUp
    source <> boundary.source
    destinationLinkUp := boundary.destinationLinkUp
    boundary.prepare <> prepare; boundary.cancel <> cancel; boundary.resume <> resume
    held := boundary.held; terminal <> boundary.terminal
    busy := boundary.busy; fault := boundary.fault
    val release = Module(new CdcResetRelease)
    release.clockIn := fabricClock; release.asyncReset := commonColdReset
    val loader = withClockAndReset(fabricClock, release.resetOut) {
        Module(new JtagRamLoader(BigInt("80200000", 16), BigInt("80210000", 16),
            exposeDmiIdle = true))
    }
    loader.io.linkUp := boundary.destinationLinkUp
    loader.io.control <> control
    memory <> loader.io.memory
    boundary.destinationOwnersIdle := loader.io.dmiOwnersIdle.get
    loaderOwnersIdle := loader.io.dmiOwnersIdle.get
    loader.io.dmi.request.valid := boundary.destination.request.valid && !holdDestinationRequest
    loader.io.dmi.request.bits := boundary.destination.request.bits
    boundary.destination.request.ready := loader.io.dmi.request.ready && !holdDestinationRequest
    boundary.destination.response.valid := loader.io.dmi.response.valid && !holdDestinationResponse
    boundary.destination.response.bits := loader.io.dmi.response.bits
    loader.io.dmi.response.ready := boundary.destination.response.ready && !holdDestinationResponse
    destinationRequestFire := loader.io.dmi.request.fire
    destinationResponseFire := loader.io.dmi.response.fire
}
object JtagLoaderAdmissionNativeMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new JtagLoaderAdmissionNative,
        Array("--target-dir", args(0)), Array("--split-verilog", "--strip-debug-info",
            "--disable-all-randomization", "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
