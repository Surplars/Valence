package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

object ProtectedFpRetirementConfig {
    val params = OooParams(robEntries = 16, tagBits = 64, commitWidth = 2, machineSystem = true,
        hypervisorExperiment = true, virtualMemoryLevels = 3, pmpEntries = 16,
        floatingPoint = FloatingPointConfig.fullFD.copy(resources = FloatingPointResourceConfig.fpga))
}

/** Test-only composition of real owner and architectural consumers, not an H+FP core.
  * Synthetic successful results qualify transport/retirement, never arithmetic.
  * Status, CSR and V transitions are idle-only; reset is cold-idle setup only.
  */
class ProtectedFpRetirementGsim extends Module {
    private val p = ProtectedFpRetirementConfig.params
    val io = IO(new Bundle {
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
        val commit0 = Input(Valid(new RobToken(p)))
        val commit1 = Input(Valid(new RobToken(p)))
        val completeAccept = Input(Bool())
        val completionAccepted = Output(Bool())
        val completionSeen = Output(Bool())
        val issueAccepted = Output(Bool())
        val ownerActive = Output(Bool())
        val ownerToken = Output(new RobToken(p))
        val contextMemoryEpoch = Output(Bool())
        val hMemoryEpoch = Output(Bool())
        val fpMemoryEpoch = Output(Bool())
        val retired = Output(Bool())
        val retireMatches = Output(UInt(2.W))
        val statePhase = Output(UInt(2.W))
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
        val fpr_0 = Output(UInt(64.W))
        val fpr_1 = Output(UInt(64.W))
        val fpr_2 = Output(UInt(64.W))
        val fpr_3 = Output(UInt(64.W))
        val fpr_4 = Output(UInt(64.W))
        val fpr_5 = Output(UInt(64.W))
        val fpr_6 = Output(UInt(64.W))
        val fpr_7 = Output(UInt(64.W))
        val fpr_8 = Output(UInt(64.W))
        val fpr_9 = Output(UInt(64.W))
        val fpr_10 = Output(UInt(64.W))
        val fpr_11 = Output(UInt(64.W))
        val fpr_12 = Output(UInt(64.W))
        val fpr_13 = Output(UInt(64.W))
        val fpr_14 = Output(UInt(64.W))
        val fpr_15 = Output(UInt(64.W))
        val fpr_16 = Output(UInt(64.W))
        val fpr_17 = Output(UInt(64.W))
        val fpr_18 = Output(UInt(64.W))
        val fpr_19 = Output(UInt(64.W))
        val fpr_20 = Output(UInt(64.W))
        val fpr_21 = Output(UInt(64.W))
        val fpr_22 = Output(UInt(64.W))
        val fpr_23 = Output(UInt(64.W))
        val fpr_24 = Output(UInt(64.W))
        val fpr_25 = Output(UInt(64.W))
        val fpr_26 = Output(UInt(64.W))
        val fpr_27 = Output(UInt(64.W))
        val fpr_28 = Output(UInt(64.W))
        val fpr_29 = Output(UInt(64.W))
        val fpr_30 = Output(UInt(64.W))
        val fpr_31 = Output(UInt(64.W))
    })
    val state = Module(new FloatingPointState(p, dualFs = true))
    val hypervisor = Module(new HypervisorState(compressed = false, guestFiles = 0, floatingPoint = true))

    val owner = Module(new ProtectedSystemOwner(p))
    // The only fixture state records downstream acceptance, not architectural state.
    // complete is a held Valid offer, while owner.complete requires a single event.
    val completionSeen = RegInit(false.B)
    val completionAccepted = state.io.complete.valid && io.completeAccept && !completionSeen
    when(completionAccepted) { completionSeen := true.B }
    when(state.io.issue.fire) { completionSeen := false.B }
    owner.io.start.valid := state.io.issue.fire
    owner.io.start.bits.token := state.io.issue.bits.token
    owner.io.start.bits.instruction := state.io.issue.bits.instruction
    owner.io.complete.valid := completionAccepted
    owner.io.complete.bits := FloatingPointResultTransport.toBackend(p, state.io.complete.bits, 0.U(64.W))
    owner.io.commits(0) := io.commit0
    owner.io.commits(1) := io.commit1
    io.completionAccepted := completionAccepted
    io.completionSeen := completionSeen
    io.issueAccepted := state.io.issue.fire
    io.ownerActive := owner.io.active
    io.ownerToken := owner.io.token
    io.contextMemoryEpoch := owner.io.contextMemoryEpoch
    io.hMemoryEpoch := owner.io.hMemoryEpoch
    io.fpMemoryEpoch := owner.io.fpMemoryEpoch
    io.retired := owner.io.retired
    io.retireMatches := owner.io.retireMatches.asUInt
    io.statePhase := BoringUtils.bore(state.state)
    val architectural = BoringUtils.bore(state.architecturalRegisters)
    io.fpr_0 := architectural(0)
    io.fpr_1 := architectural(1)
    io.fpr_2 := architectural(2)
    io.fpr_3 := architectural(3)
    io.fpr_4 := architectural(4)
    io.fpr_5 := architectural(5)
    io.fpr_6 := architectural(6)
    io.fpr_7 := architectural(7)
    io.fpr_8 := architectural(8)
    io.fpr_9 := architectural(9)
    io.fpr_10 := architectural(10)
    io.fpr_11 := architectural(11)
    io.fpr_12 := architectural(12)
    io.fpr_13 := architectural(13)
    io.fpr_14 := architectural(14)
    io.fpr_15 := architectural(15)
    io.fpr_16 := architectural(16)
    io.fpr_17 := architectural(17)
    io.fpr_18 := architectural(18)
    io.fpr_19 := architectural(19)
    io.fpr_20 := architectural(20)
    io.fpr_21 := architectural(21)
    io.fpr_22 := architectural(22)
    io.fpr_23 := architectural(23)
    io.fpr_24 := architectural(24)
    io.fpr_25 := architectural(25)
    io.fpr_26 := architectural(26)
    io.fpr_27 := architectural(27)
    io.fpr_28 := architectural(28)
    io.fpr_29 := architectural(29)
    io.fpr_30 := architectural(30)
    io.fpr_31 := architectural(31)

    state.io.headAuthorized := true.B
    state.io.flush := false.B
    state.io.guestContext.get.virtualized := hypervisor.io.virtualized
    state.io.guestContext.get.fs := hypervisor.io.floatingPoint.get.fs
    hypervisor.io.floatingPoint.get.mutation := state.io.mutation.get
    io.mutation := state.io.mutation.get

    // The exact production helper is shared with MachineSystemUnit. No private
    // fixture alias predicate substitutes for the host-FS ownership decision.
    io.status.ready := !state.io.busy
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
    // Deliberately no owner-active qualifier: retain the production raw grant contract.
    state.io.retire.valid := owner.io.retired
    state.io.retire.bits := owner.io.token
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

    assert(!(state.io.busy && (io.status.valid || io.csr.valid || io.mret || io.sret)),
        "status CSR and V setup must be idle")
    when(io.result.fire) { assert(!io.result.bits.exception, "successful synthetic results only") }
    when(state.io.complete.valid) { assert(!state.io.complete.bits.exception, "successful FP commands only") }

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

object ProtectedFpRetirementGsimMain extends App {
    require(args.length == 1, "output-directory")
    ChiselStage.emitCHIRRTLFile(new ProtectedFpRetirementGsim, Array("--target-dir", args.head))
}
