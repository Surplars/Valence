package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._
import soc.ip.interrupt.{AplicParams, ImsicParams}
import soc.platform.CommonInterruptFabric
import soc.ip.bus.RegisterPort

/** Actual two-issue OoO ROB, real APLIC pair and IMSIC. Instructions come from
  * the test ROM at Bare addresses; this fixture does not qualify translated fetch.
  * Interrupts originate only at the physical source pins or real APLIC registers.
  */
class AiaRetiringCoreGsim extends Module {
    val p = OooParams(hypervisorExperiment = true, robEntries = 16, physicalRegs = 48, memoryEntries = 2,
        machineSystem = true, virtualMemoryLevels = 3, pmpEntries = 16)
    val io = IO(new Bundle {
        val programWrite = Input(Bool())
        val programIndex = Input(UInt(10.W))
        val programData = Input(UInt(32.W))
        val programHold = Input(Bool())
        val fetchPc = Output(UInt(64.W))
        val commitEnable = Input(Bool())
        val commit0 = Output(Valid(new CommitRecord(p)))
        val commit1 = Output(Valid(new CommitRecord(p)))
        val trap = Output(Valid(new HeadException(p)))
        val virtualized = Output(Bool())
        val privilege = Output(UInt(2.W))
        val memoryRequest = Output(Bool())
        val sources = Input(UInt(8.W))
        val machineRegisters = Flipped(new RegisterPort)
        val supervisorRegisters = Flipped(new RegisterPort)
        val allowMsi = Input(Bool())
        val allowMsiResponse = Input(Bool())
        val msiValid = Output(Bool())
        val msiFire = Output(Bool())
        val msiAddress = Output(UInt(64.W))
        val msiData = Output(UInt(64.W))
        val msiResponseValid = Output(Bool())
        val msiResponseData = Output(UInt(64.W))
        val msiResponseFire = Output(Bool())
        val msiResponseError = Output(Bool())
        val msiError = Output(Bool())
    })
    val imsicParams = ImsicParams(guestFiles = 3)
    val core = Module(new MachineCore(p, imsicParams, experimentalHypervisor = true))
    val fabric = Module(new CommonInterruptFabric(AplicParams(sources = 8), imsicParams))
    fabric.io.sources := io.sources
    fabric.io.machineRegisters <> io.machineRegisters
    fabric.io.supervisorRegisters <> io.supervisorRegisters
    val program = Mem(1024, UInt(32.W))
    when(io.programWrite) { program.write(io.programIndex, io.programData) }
    for (lane <- 0 until 2) {
        val pc = core.io.fetchPc + (lane * 4).U
        core.io.instructions(lane).valid := !io.programHold && pc >= "h80000000".U && pc < "h80001000".U
        core.io.instructions(lane).bits := program(pc(11, 2))
    }
    core.io.guestDataFault.get := 0.U.asTypeOf(new GuestFaultMetadata)
    core.io.guestInstructionFault.get := 0.U.asTypeOf(core.io.guestInstructionFault.get)
    core.io.instructionFaults := VecInit(Seq.fill(2)(false.B))
    core.io.instructionPageFaults := VecInit(Seq.fill(2)(false.B))
    core.io.timerInterrupt := false.B; core.io.timeValue := 0.U
    core.io.fetchQuiescent.get := true.B
    core.io.vmFlushReady.get := true.B; core.io.fenceIFlushReady := true.B
    core.io.commitEnable := io.commitEnable && !io.programHold; core.io.inspectRegister := 0.U
    core.io.memory.request.ready := true.B
    core.io.memory.response.valid := false.B
    core.io.memory.response.bits := 0.U.asTypeOf(core.io.memory.response.bits)
    core.io.msi.request.valid := fabric.io.msi.request.valid && io.allowMsi
    core.io.msi.request.bits := fabric.io.msi.request.bits
    fabric.io.msi.request.ready := core.io.msi.request.ready && io.allowMsi
    fabric.io.msi.response.valid := core.io.msi.response.valid && io.allowMsiResponse
    fabric.io.msi.response.bits := core.io.msi.response.bits
    core.io.msi.response.ready := fabric.io.msi.response.ready && io.allowMsiResponse
    io.msiValid := fabric.io.msi.request.valid
    io.msiFire := fabric.io.msi.request.fire
    io.msiAddress := fabric.io.msi.request.bits.address
    io.msiData := fabric.io.msi.request.bits.data
    io.msiResponseValid := core.io.msi.response.valid
    io.msiResponseData := core.io.msi.response.bits.data
    io.msiResponseFire := core.io.msi.response.fire
    io.msiResponseError := core.io.msi.response.bits.error
    io.msiError := fabric.io.msiError
    io.fetchPc := core.io.fetchPc
    io.commit0 := core.io.commit(0); io.commit1 := core.io.commit(1)
    io.trap := core.io.trap
    io.virtualized := core.io.virtualized.get; io.privilege := core.io.fetchPrivilege.get
    io.memoryRequest := core.io.memory.request.valid
}
object AiaRetiringCoreGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new AiaRetiringCoreGsim, Array("--target-dir", args(0)))
}
