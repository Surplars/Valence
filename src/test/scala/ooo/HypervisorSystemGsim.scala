package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._
import soc.ip.interrupt.{Imsic, ImsicParams}

/** Actual ROB-head-authorized system unit + IMSIC, without a fake CSR implementation. */
class HypervisorSystemGsim extends Module {
    private val p = OooParams(hypervisorExperiment = true, machineSystem = true, virtualMemoryLevels = 3, pmpEntries = 16)
    val io = IO(new Bundle {
        val start = Input(Bool())
        val instruction = Input(UInt(32.W))
        val operand = Input(UInt(64.W))
        val pc = Input(UInt(64.W))
        val ready = Output(Bool())
        val completeReady = Input(Bool())
        val complete = Output(Bool())
        val data = Output(UInt(64.W))
        val exception = Output(Bool())
        val cause = Output(UInt(64.W))
        val tval = Output(UInt(64.W))
        val nextPc = Output(UInt(64.W))
        val redirect = Output(Bool())
        val trap = Input(Bool())
        val trapPc = Input(UInt(64.W))
        val trapCause = Input(UInt(64.W))
        val trapTval = Input(UInt(64.W))
        val trapReady = Output(Bool())
        val trapTarget = Output(UInt(64.W))
        val privilege = Output(UInt(2.W))
        val virtualized = Output(Bool())
        val interruptPending = Output(Bool())
        val interruptCause = Output(UInt(6.W))
        val guestExternal = Input(UInt(3.W))
        val hostExternal = Input(Bool())
        val time = Input(UInt(64.W))
    })
    val system = Module(new MachineSystemUnit(p, experimentalHypervisor = true, guestFiles = 3))
    val imsic = Module(new Imsic(ImsicParams(guestFiles = 3)))
    system.io.start.valid := io.start
    system.io.start.bits.token := 0.U.asTypeOf(system.io.start.bits.token)
    system.io.start.bits.instruction := io.instruction
    system.io.start.bits.operand := io.operand
    system.io.start.bits.operand2.get := 0.U
    system.io.hMemory.get.request.ready := false.B
    system.io.hMemory.get.response.valid := false.B
    system.io.hMemory.get.response.bits := 0.U.asTypeOf(system.io.hMemory.get.response.bits)
    system.io.hMemoryFault.get := 0.U.asTypeOf(new GuestFaultMetadata)
    system.io.start.bits.pc := io.pc
    io.ready := system.io.start.ready
    system.io.complete.ready := io.completeReady
    io.complete := system.io.complete.valid
    io.data := system.io.complete.bits.completion.data
    io.exception := system.io.complete.bits.completion.exception
    io.cause := system.io.complete.bits.completion.cause
    io.tval := system.io.complete.bits.completion.tval
    io.nextPc := system.io.complete.bits.completion.nextPc
    io.redirect := system.io.complete.bits.redirect
    system.io.imsic.request <> imsic.io.csrRequest
    system.io.imsic.response <> imsic.io.csrResponse
    imsic.io.mmio.request.valid := false.B
    imsic.io.mmio.request.bits := 0.U.asTypeOf(imsic.io.mmio.request.bits)
    imsic.io.mmio.response.ready := true.B
    system.io.trap.valid := io.trap
    system.io.trap.bits.token := 0.U.asTypeOf(system.io.trap.bits.token)
    system.io.trap.bits.pc := io.trapPc
    system.io.trap.bits.cause := io.trapCause
    system.io.trap.bits.tval := io.trapTval
    system.io.trap.bits.guestFault.get := 0.U.asTypeOf(new GuestFaultMetadata)
    io.trapReady := system.io.trapReady; io.trapTarget := system.io.trapTarget
    system.io.externalInterrupt := false.B
    system.io.supervisorExternalInterrupt := io.hostExternal
    system.io.timerInterrupt := false.B
    system.io.guestExternal.get := io.guestExternal
    system.io.guestTopIdentities.get := imsic.io.topIdentities(54, 22)
    system.io.timeValue := io.time
    system.io.vmFlushReady.get := true.B
    system.io.fenceIFlushReady := true.B
    io.privilege := system.io.fetchPrivilege; io.virtualized := system.io.virtualized.get
    io.interruptPending := system.io.interruptPending; io.interruptCause := system.io.interruptCause
}
object HypervisorSystemGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new HypervisorSystemGsim, Array("--target-dir", args(0)))
}
