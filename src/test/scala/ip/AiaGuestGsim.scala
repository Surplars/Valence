package ip

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.bus._
import soc.ip.interrupt._
import soc.platform.CommonInterruptFabric

/** Complete two-domain APLIC -> IMSIC path, with test-only MSI backpressure.
  * No architectural state is inspected directly; the oracle uses MMIO and CSRs.
  */
class AiaGuestGsim(guests: Int) extends Module {
    val imsicParams = ImsicParams(guestFiles = guests)
    val io = IO(new Bundle {
        val sources = Input(UInt(8.W))
        val machine = Flipped(new RegisterPort)
        val supervisor = Flipped(new RegisterPort)
        val injection = Flipped(new RegisterPort)
        val csrRequest = Flipped(Decoupled(new ImsicCsrRequest))
        val csrResponse = Decoupled(new RegisterResponse)
        val allowMsi = Input(Bool())
        val allowMsiResponse = Input(Bool())
        val msiValid = Output(Bool()); val msiFire = Output(Bool())
        val msiAddress = Output(UInt(64.W)); val msiData = Output(UInt(64.W))
        val interrupts = Output(UInt(imsicParams.files.W))
        val msiError = Output(Bool())
    })
    val fabric = Module(new CommonInterruptFabric(AplicParams(sources = 8), imsicParams))
    val imsic = Module(new Imsic(imsicParams))
    val arbiter = Module(new TwoMasterRegisterArbiter(lockRequests = true, resetRoundRobin = true))
    fabric.io.sources := io.sources
    fabric.io.machineRegisters <> io.machine
    fabric.io.supervisorRegisters <> io.supervisor
    arbiter.io.masters(0).request.valid := fabric.io.msi.request.valid && io.allowMsi
    arbiter.io.masters(0).request.bits := fabric.io.msi.request.bits
    fabric.io.msi.request.ready := arbiter.io.masters(0).request.ready && io.allowMsi
    fabric.io.msi.response.valid := arbiter.io.masters(0).response.valid && io.allowMsiResponse
    fabric.io.msi.response.bits := arbiter.io.masters(0).response.bits
    arbiter.io.masters(0).response.ready := fabric.io.msi.response.ready && io.allowMsiResponse
    arbiter.io.masters(1) <> io.injection
    imsic.io.mmio <> arbiter.io.downstream
    imsic.io.csrRequest <> io.csrRequest
    imsic.io.csrResponse <> io.csrResponse
    io.interrupts := imsic.io.interrupts
    io.msiError := fabric.io.msiError
    io.msiValid := fabric.io.msi.request.valid
    io.msiFire := fabric.io.msi.request.fire
    io.msiAddress := fabric.io.msi.request.bits.address
    io.msiData := fabric.io.msi.request.bits.data
}

object AiaGuestGsimMain extends App {
    require(args.length == 2)
    ChiselStage.emitCHIRRTLFile(new AiaGuestGsim(args(1).toInt), Array("--target-dir", args(0)))
}
