package ip

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.bus.RegisterPort
import soc.ip.interrupt.{AplicParams, Imsic, ImsicCsrRequest, ImsicParams, MsiAdmissionBarrier}
import soc.platform.CommonInterruptFabric

/** Real APLIC pair and IMSIC. The only synthetic behavior is transport stalls.
  * The test observes architectural MMIO/CSR, not private interrupt state.
  */
class MsiAdmissionBarrierNative extends Module {
    val io = IO(new Bundle {
        val stop = Input(Bool())
        val sources = Input(UInt(8.W))
        val allowRequest = Input(Bool())
        val allowReply = Input(Bool())
        val allowTerminal = Input(Bool())
        val machineRegisters = Flipped(new RegisterPort)
        val supervisorRegisters = Flipped(new RegisterPort)
        val csrRequest = Flipped(Decoupled(new ImsicCsrRequest))
        val csrResponse = Decoupled(new soc.ip.bus.RegisterResponse)
        val idle = Output(Bool())
        val upstreamPending = Output(Bool())
        val destinationValid = Output(Bool())
        val destinationReady = Output(Bool())
        val destinationIdentity = Output(UInt(64.W))
        val destinationAddress = Output(UInt(64.W))
        val sourceReplyValid = Output(Bool())
        val sourceReplyReady = Output(Bool())
        val accepted = Output(Bool())
        val acceptedIdentity = Output(UInt(64.W))
        val acceptedAddress = Output(UInt(64.W))
        val issued = Output(Bool())
        val consumed = Output(Bool())
        val interrupts = Output(UInt(2.W))
        val msiError = Output(Bool())
    })
    val fabric = Module(new CommonInterruptFabric(AplicParams(sources = 8, identities = 63),
        ImsicParams(identities = 63)))
    val barrier = Module(new MsiAdmissionBarrier(capacity = 2))
    val imsic = Module(new Imsic(ImsicParams(identities = 63)))
    fabric.io.sources := io.sources
    fabric.io.machineRegisters <> io.machineRegisters
    fabric.io.supervisorRegisters <> io.supervisorRegisters
    barrier.io.stop := io.stop
    barrier.io.source.request <> fabric.io.msi.request
    fabric.io.msi.response.valid := barrier.io.source.response.valid && io.allowTerminal
    fabric.io.msi.response.bits := barrier.io.source.response.bits
    barrier.io.source.response.ready := fabric.io.msi.response.ready && io.allowTerminal
    imsic.io.mmio.request.valid := barrier.io.destination.request.valid && io.allowRequest
    imsic.io.mmio.request.bits := barrier.io.destination.request.bits
    barrier.io.destination.request.ready := imsic.io.mmio.request.ready && io.allowRequest
    barrier.io.destination.response.valid := imsic.io.mmio.response.valid && io.allowReply
    barrier.io.destination.response.bits := imsic.io.mmio.response.bits
    imsic.io.mmio.response.ready := barrier.io.destination.response.ready && io.allowReply
    io.csrRequest <> imsic.io.csrRequest
    io.csrResponse <> imsic.io.csrResponse
    io.idle := barrier.io.idle
    io.upstreamPending := fabric.io.msi.request.valid
    io.destinationValid := barrier.io.destination.request.valid
    io.destinationReady := barrier.io.destination.request.ready
    io.destinationIdentity := barrier.io.destination.request.bits.data
    io.destinationAddress := barrier.io.destination.request.bits.address
    io.sourceReplyValid := barrier.io.source.response.valid
    io.sourceReplyReady := barrier.io.source.response.ready
    io.accepted := barrier.io.source.request.fire
    io.acceptedIdentity := barrier.io.source.request.bits.data
    io.acceptedAddress := barrier.io.source.request.bits.address
    io.issued := barrier.io.destination.request.fire
    io.consumed := barrier.io.source.response.fire
    io.interrupts := imsic.io.interrupts
    io.msiError := fabric.io.msiError
}

/** CHIRRTL is lowered by the runner with the explicit pinned native firtool. */
object MsiAdmissionBarrierNativeMain extends App {
    require(args.length == 1, "explicit fresh output directory required")
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    ChiselStage.emitCHIRRTLFile(new MsiAdmissionBarrierNative, Array("--target-dir", args(0)))
}
