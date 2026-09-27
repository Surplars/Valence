package ip

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.ip.bus.{RegisterPort, TwoMasterRegisterArbiter, RegisterResponse}
import soc.ip.interrupt.{Aplic, AplicParams, Imsic, ImsicCsrRequest, ImsicParams}
import soc.ip.uart.UartConsole

/** M root delegates UART source 3 to an S child that sends an MSI to the S interrupt file. */
class AiaSupervisorUartGsim extends Module {
    val io = IO(new Bundle {
        val machine = Flipped(new RegisterPort)
        val supervisor = Flipped(new RegisterPort)
        val uartRegisters = Flipped(new RegisterPort)
        val csrRequest = Flipped(Decoupled(new ImsicCsrRequest))
        val csrResponse = Decoupled(new RegisterResponse)
        val uartRx = Input(Bool())
        val machineInterrupt = Output(Bool())
        val supervisorInterrupt = Output(Bool())
        val childEnabled = Output(UInt(31.W))
    })
    val imsicParams = ImsicParams()
    val root = Module(new Aplic(AplicParams(), hasChild = true,
        childMsiBase = imsicParams.supervisorBase))
    val child = Module(new Aplic(AplicParams(base = BigInt("0c004000", 16),
        msiBase = imsicParams.supervisorBase), hasParent = true))
    val imsic = Module(new Imsic(imsicParams))
    val arbiter = Module(new TwoMasterRegisterArbiter)
    val uart = Module(new UartConsole)
    root.io.mmio <> io.machine
    child.io.mmio <> io.supervisor
    uart.io.mmio <> io.uartRegisters
    uart.io.rx := io.uartRx
    root.io.sources := uart.io.irq.asUInt << 2
    child.io.sources := root.io.childSources
    child.io.parentEnabled.get := root.io.childEnabled
    io.childEnabled := root.io.childEnabled
    arbiter.io.masters(0) <> root.io.msi
    arbiter.io.masters(1) <> child.io.msi
    imsic.io.mmio <> arbiter.io.downstream
    imsic.io.csrRequest <> io.csrRequest
    io.csrResponse <> imsic.io.csrResponse
    io.machineInterrupt := imsic.io.interrupts(0)
    io.supervisorInterrupt := imsic.io.interrupts(1)
    assert(!root.io.msiError && !child.io.msiError, "APLIC MSI failed")
}

object AiaSupervisorUartGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new AiaSupervisorUartGsim, Array("--target-dir", args.head))
}
