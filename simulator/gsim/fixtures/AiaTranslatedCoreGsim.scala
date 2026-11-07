package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._
import soc.ip.bus.RegisterPort
import soc.ip.interrupt.{AplicParams, ImsicParams}
import soc.platform.CommonInterruptFabric

/** Same-DUT APLIC -> IMSIC -> OoO retirement with the production scalar C
  * assembler and both actual nested translation services. External IF, data,
  * and PTE endpoints remain physical; no translated-memory behavior is mocked.
  */
class AiaTranslatedCoreGsim extends Module {
    val core = Module(new HypervisorMachineCore)
    val io = IO(new Bundle {
        val cpu = chiselTypeOf(core.io)
        val sources = Input(UInt(8.W))
        val machineRegisters = Flipped(new RegisterPort)
        val supervisorRegisters = Flipped(new RegisterPort)
        val allowMsi = Input(Bool())
        val allowMsiResponse = Input(Bool())
        val msiValid = Output(Bool())
        val msiReady = Output(Bool())
        val msiFire = Output(Bool())
        val msiAddress = Output(UInt(64.W))
        val msiWrite = Output(Bool())
        val msiSize = Output(UInt(3.W))
        val msiData = Output(UInt(64.W))
        val msiByteEnable = Output(UInt(8.W))
        val msiResponseValid = Output(Bool())
        val msiResponseReady = Output(Bool())
        val msiResponseData = Output(UInt(64.W))
        val msiResponseFire = Output(Bool())
        val msiResponseError = Output(Bool())
        val msiError = Output(Bool())
    })
    io.cpu <> core.io

    // Identical physical RAM PMA policy to HypervisorTranslatedCoreGsim.
    def ram(address: UInt): Bool = address >= "h80000000".U && address < "h81000000".U
    core.io.dataPmaDenied := !ram(core.io.dataPhysicalCheck.bits.address)
    core.io.fetchPmaDenied := !ram(core.io.fetchPhysicalCheck.bits.address)
    core.io.dataPmaUncached := false.B
    core.io.timerInterrupt := false.B
    core.io.timeValue := 0.U

    val fabric = Module(new CommonInterruptFabric(AplicParams(sources = 8), ImsicParams(guestFiles = 3)))
    fabric.io.sources := io.sources
    fabric.io.machineRegisters <> io.machineRegisters
    fabric.io.supervisorRegisters <> io.supervisorRegisters

    // Gate complete handshakes in both directions. The core's cloned MSI input
    // pins are deliberately ignored: every accepted MSI comes from this fabric.
    core.io.msi.request.valid := fabric.io.msi.request.valid && io.allowMsi
    core.io.msi.request.bits := fabric.io.msi.request.bits
    fabric.io.msi.request.ready := core.io.msi.request.ready && io.allowMsi
    fabric.io.msi.response.valid := core.io.msi.response.valid && io.allowMsiResponse
    fabric.io.msi.response.bits := core.io.msi.response.bits
    core.io.msi.response.ready := fabric.io.msi.response.ready && io.allowMsiResponse

    // Observe the offered request and real IMSIC reply before each stall gate.
    // Ready/fire are the actual fabric-request and core-response handshakes.
    io.msiValid := fabric.io.msi.request.valid
    io.msiReady := fabric.io.msi.request.ready
    io.msiFire := fabric.io.msi.request.fire
    io.msiAddress := fabric.io.msi.request.bits.address
    io.msiWrite := fabric.io.msi.request.bits.write
    io.msiSize := fabric.io.msi.request.bits.size
    io.msiData := fabric.io.msi.request.bits.data
    io.msiByteEnable := fabric.io.msi.request.bits.byteEnable
    io.msiResponseValid := core.io.msi.response.valid
    io.msiResponseReady := core.io.msi.response.ready
    io.msiResponseData := core.io.msi.response.bits.data
    io.msiResponseFire := core.io.msi.response.fire
    io.msiResponseError := core.io.msi.response.bits.error
    io.msiError := fabric.io.msiError
}

object AiaTranslatedCoreGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new AiaTranslatedCoreGsim, Array("--target-dir", args(0)))
}
