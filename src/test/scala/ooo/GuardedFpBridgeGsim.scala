package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

object GuardedFpBridgeConfig {
    val params = OooParams(robEntries = 16, tagBits = 64, commitWidth = 2, machineSystem = true,
        hypervisorExperiment = true, virtualMemoryLevels = 3, pmpEntries = 16,
        floatingPoint = FloatingPointConfig.fullFD.copy(multiply = false, divide = false, squareRoot = false,
            fusedMultiplyAdd = false, conversions = false, memory = false,
            resources = FloatingPointResourceConfig.fpga))
}

/** Real arithmetic bridge with passive architectural observations. Not an H+FP core.
  * Context/CSR setup is idle-only; owner captures real start/complete handshakes.
  */
class GuardedFpBridgeGsim extends Module {
    private val p = GuardedFpBridgeConfig.params
    val io = IO(new Bundle {
        val start = Flipped(Decoupled(new SystemRequest(p)))
        val complete = Decoupled(new BackendCompletion(p))
        val translationActive = Input(Bool())
        val commit0 = Input(Valid(new RobToken(p)))
        val commit1 = Input(Valid(new RobToken(p)))
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
    val system = Module(new FloatingPointSystem(p, dualFs = true))
    val hypervisor = Module(new HypervisorState(compressed = false, guestFiles = 0, floatingPoint = true))
    val owner = Module(new ProtectedSystemOwner(p))
    owner.io.start.valid := system.io.start.fire
    owner.io.start.bits.token := system.io.start.bits.token
    owner.io.start.bits.instruction := system.io.start.bits.instruction
    owner.io.complete.valid := system.io.complete.fire
    owner.io.complete.bits := system.io.complete.bits
    owner.io.commits(0) := io.commit0
    owner.io.commits(1) := io.commit1
    io.completionAccepted := system.io.complete.fire
    io.completionSeen := BoringUtils.bore(system.sent)
    io.issueAccepted := system.io.start.fire
    io.ownerActive := owner.io.active
    io.ownerToken := owner.io.token
    io.contextMemoryEpoch := owner.io.contextMemoryEpoch
    io.hMemoryEpoch := owner.io.hMemoryEpoch
    io.fpMemoryEpoch := owner.io.fpMemoryEpoch
    io.retired := owner.io.retired
    io.retireMatches := owner.io.retireMatches.asUInt
    io.statePhase := BoringUtils.bore(system.fp.state)
    val architectural = BoringUtils.bore(system.fp.architecturalRegisters)
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

    system.io.trap := false.B
    system.io.guestContext.get.virtualized := hypervisor.io.virtualized
    system.io.guestContext.get.fs := hypervisor.io.floatingPoint.get.fs
    hypervisor.io.floatingPoint.get.mutation := system.io.mutation.get
    io.mutation := system.io.mutation.get

    // The exact production helper is shared with MachineSystemUnit. No private
    // fixture alias predicate substitutes for the host-FS ownership decision.
    io.status.ready := !system.io.busy
    system.io.setFs.valid := io.status.valid &&
        FloatingPointStatus.writesHost(io.status.bits.address, hypervisor.io.virtualized)
    system.io.setFs.bits := io.status.bits.data(14, 13)
    hypervisor.io.write.valid := io.status.fire
    hypervisor.io.write.bits := io.status.bits
    system.io.csr.valid := io.csr.valid && !io.status.valid
    system.io.csr.bits := io.csr.bits
    io.csr.ready := system.io.csr.ready && !io.status.valid
    io.csrRead := BoringUtils.bore(system.fp.io.csrRead)
    io.csrIllegal := BoringUtils.bore(system.fp.io.csrIllegal)
    system.io.start.valid := io.start.valid && !io.status.valid
    system.io.start.bits := io.start.bits
    io.start.ready := system.io.start.ready && !io.status.valid
    io.complete <> system.io.complete
    // Architectural V is independent from the translation-active input.
    system.io.virtualized := io.translationActive
    system.io.dataPrivilege := 1.U
    system.io.pmpState := 0.U.asTypeOf(new PmpState)
    system.io.guestAddress.get := false.B
    system.io.guestFault.get := 0.U.asTypeOf(new GuestFaultMetadata)
    system.io.memory.request.ready := false.B
    system.io.memory.response.valid := false.B
    system.io.memory.response.bits := 0.U.asTypeOf(system.io.memory.response.bits)
    // Deliberately no owner-active qualifier: retain the production raw grant contract.
    system.io.retire.valid := owner.io.retired
    system.io.retire.bits := owner.io.token
    io.retireAccepted := BoringUtils.bore(system.fp.io.retireAccepted)
    io.hostFs := system.io.fs
    io.hostSd := system.io.fs === 3.U
    io.guestFs := hypervisor.io.floatingPoint.get.fs
    io.guestSd := hypervisor.io.floatingPoint.get.sd
    io.fcsr := system.io.fcsr
    io.busy := system.io.busy
    io.virtualized := hypervisor.io.virtualized
    hypervisor.io.readAddress := io.statusReadAddress
    io.statusShadow := hypervisor.io.shadow
    // Only FS/SD are projected for the host bank; other host mstatus fields are
    // outside this component fixture. Guest status is the production H read path.
    io.statusReadData := Mux(FloatingPointStatus.writesHost(io.statusReadAddress, hypervisor.io.virtualized),
        FloatingPointStatus.bits(system.io.fs), hypervisor.io.readData)

    assert(!((system.io.busy || owner.io.active) && (io.status.valid || io.csr.valid || io.mret || io.sret)),
        "status CSR and V setup must be idle")
    when(system.io.complete.valid) { assert(!system.io.complete.bits.exception, "successful FP commands only") }

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

object GuardedFpBridgeGsimMain extends App {
    require(args.length == 1, "output-directory")
    ChiselStage.emitCHIRRTLFile(new GuardedFpBridgeGsim, Array("--target-dir", args.head))
}
