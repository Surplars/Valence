package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Component preparation only: genuine FP state and H state, never an H+FP core.
  * Result inputs are explicit synthetic producer stimulation, not arithmetic.
  * Status writes have already passed privilege/write-intent checks at the caller.
  * Returns may perturb live V while FP is busy to test captured owner transport;
  * this does not assert that such a sequence is a legal actual-core lifecycle.
  */
class DualFsPreparationGsim extends Module {
    private val p = OooParams(robEntries = 16, tagBits = 64, machineSystem = true,
        floatingPoint = FloatingPointConfig.fullFD.copy(resources = FloatingPointResourceConfig.fpga))
    val io = IO(new Bundle {
        val headAuthorized = Input(Bool())
        val flush = Input(Bool())
        val issue = Flipped(Decoupled(new ScalarFloatingPointCommand(p)))
        val execute = Decoupled(new Bundle {
            val command = new ScalarFloatingPointCommand(p)
            val operands_0 = UInt(64.W)
            val operands_1 = UInt(64.W)
            val operands_2 = UInt(64.W)
            val rounding = UInt(3.W)
        })
        val result = Flipped(Decoupled(new FloatingPointResult(p)))
        val complete = Output(Valid(new FloatingPointResult(p)))
        val retire = Input(Valid(new RobToken(p)))
        val retireAccepted = Output(Bool())
        val csr = Flipped(Decoupled(new FloatingPointCsr))
        val csrRead = Output(UInt(64.W))
        val csrIllegal = Output(Bool())
        val status = Flipped(Decoupled(new GuestInterruptCsrWrite))
        val statusReadAddress = Input(UInt(12.W))
        val statusReadData = Output(UInt(64.W))
        val statusShadow = Output(Bool())
        val mret = Input(Bool())
        val sret = Input(Bool())
        val virtualized = Output(Bool())
        val hostFs = Output(UInt(2.W))
        val hostSd = Output(Bool())
        val guestFs = Output(UInt(2.W))
        val guestSd = Output(Bool())
        val mutation = Output(Valid(new FloatingPointMutation))
        val fcsr = Output(UInt(8.W))
        val busy = Output(Bool())
    })
    val state = Module(new FloatingPointState(p, dualFs = true))
    val hypervisor = Module(new HypervisorState(compressed = false, guestFiles = 0, floatingPoint = true))

    state.io.headAuthorized := io.headAuthorized
    state.io.flush := io.flush
    state.io.guestContext.get.virtualized := hypervisor.io.virtualized
    state.io.guestContext.get.fs := hypervisor.io.floatingPoint.get.fs
    hypervisor.io.floatingPoint.get.mutation := state.io.mutation.get
    io.mutation := state.io.mutation.get

    // The exact production helper is shared with MachineSystemUnit. No private
    // fixture alias predicate substitutes for the host-FS ownership decision.
    io.status.ready := !state.io.busy && io.headAuthorized && !io.flush
    state.io.setFs.valid := io.status.valid &&
        FloatingPointStatus.writesHost(io.status.bits.address, hypervisor.io.virtualized)
    state.io.setFs.bits := io.status.bits.data(14, 13)
    hypervisor.io.write.valid := io.status.fire
    hypervisor.io.write.bits := io.status.bits
    state.io.csr.valid := io.csr.valid && !io.status.valid
    state.io.csr.bits := io.csr.bits
    io.csr.ready := state.io.csr.ready && !io.status.valid
    io.csrRead := state.io.csrRead
    io.csrIllegal := state.io.csrIllegal
    state.io.issue.valid := io.issue.valid && !io.status.valid
    io.issue.ready := state.io.issue.ready && !io.status.valid
    private val issue = state.io.issue.bits
    private val in = io.issue.bits
    issue.token := in.token
    issue.instruction := in.instruction
    issue.sources := VecInit(in.sourcePorts)
    issue.checkSingleBox := VecInit(in.boxPorts)
    issue.integerSource := in.integerSource
    issue.destination := in.destination
    issue.singleResult := in.singleResult
    issue.writesFp := in.writesFp
    issue.writesFlags := in.writesFlags
    issue.usesRounding := in.usesRounding
    issue.rounding := in.rounding
    io.execute.valid := state.io.execute.valid
    state.io.execute.ready := io.execute.ready
    private val command = state.io.execute.bits.command
    private val out = io.execute.bits.command
    out.token := command.token
    out.instruction := command.instruction
    out.sourcePorts.zipWithIndex.foreach { case (port, i) => port := command.sources(i) }
    out.boxPorts.zipWithIndex.foreach { case (port, i) => port := command.checkSingleBox(i) }
    out.integerSource := command.integerSource
    out.destination := command.destination
    out.singleResult := command.singleResult
    out.writesFp := command.writesFp
    out.writesFlags := command.writesFlags
    out.usesRounding := command.usesRounding
    out.rounding := command.rounding
    io.execute.bits.operands_0 := state.io.execute.bits.operands(0)
    io.execute.bits.operands_1 := state.io.execute.bits.operands(1)
    io.execute.bits.operands_2 := state.io.execute.bits.operands(2)
    io.execute.bits.rounding := state.io.execute.bits.rounding
    state.io.result <> io.result
    io.complete := state.io.complete
    state.io.retire := io.retire
    io.retireAccepted := state.io.retireAccepted
    io.hostFs := state.io.fs
    io.hostSd := state.io.sd
    io.guestFs := hypervisor.io.floatingPoint.get.fs
    io.guestSd := hypervisor.io.floatingPoint.get.sd
    io.fcsr := state.io.fcsr
    io.busy := state.io.busy
    io.virtualized := hypervisor.io.virtualized
    hypervisor.io.readAddress := io.statusReadAddress
    io.statusShadow := hypervisor.io.shadow
    // Only FS/SD are projected for the host bank; other host mstatus fields are
    // outside this component fixture. Guest status is the production H read path.
    io.statusReadData := Mux(FloatingPointStatus.writesHost(io.statusReadAddress, hypervisor.io.virtualized),
        FloatingPointStatus.bits(state.io.fs), hypervisor.io.readData)

    hypervisor.io.privilege := 1.U
    hypervisor.io.mpp := 3.U
    hypervisor.io.mprv := false.B
    hypervisor.io.hsGlobalEnable := false.B
    hypervisor.io.machineStce := false.B
    hypervisor.io.time := 0.U
    hypervisor.io.guestExternal := 0.U
    hypervisor.io.nominatedGuestInterrupt := false.B
    hypervisor.io.nominatedGuestCause := 0.U
    hypervisor.io.mret := io.mret
    hypervisor.io.sret := io.sret
    hypervisor.io.trap.valid := false.B
    hypervisor.io.trap.bits := 0.U.asTypeOf(new HypervisorFault)
    hypervisor.io.delegated := false.B
}

object DualFsPreparationGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new DualFsPreparationGsim, Array("--target-dir", args(0)))
}
