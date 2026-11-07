package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._
import soc.ip.memory.NativeMemoryPort

object GuardedGuestFpCoreConfig {
    val params: OooParams = GuardedGuestFpCoreProfile.params
}

/** Instruction-fetched production core with read-only qualification probes.
  * Only external memory service, enable and real retirement backpressure are inputs.
  * Architectural state, issue, completions, retirement and traps have no test drivers.
  * One inherited clock/reset; IRQ/MSI/time are inactive and PMA is the fixed RAM window.
  */
class GuardedGuestFpCoreGsim(arithmetic: Boolean = false, multiply: Boolean = false) extends Module {
    require(!(arithmetic && multiply), "qualification selectors are mutually exclusive")
    private val p = if (multiply) GuardedGuestFpMultiplyProfile.params
        else if (arithmetic) GuardedGuestFpArithmeticProfile.params else GuardedGuestFpCoreConfig.params
    val io = IO(new Bundle {
        val enable = Input(Bool())
        val commitEnable = Input(Bool())
        val instruction = new GuestScalarFetchPort(2)
        val data = new NativeMemoryPort
        val fetchPte = new SvPteReadPort
        val dataPte = new SvPteReadPort
        val commit0 = Output(Valid(new CommitRecord(p)))
        val commit1 = Output(Valid(new CommitRecord(p)))
        val trap = Output(Valid(new HeadException(p)))
        val fetchPc = Output(UInt(64.W))
        val virtualized = Output(Bool())
        val privilege = Output(UInt(2.W))
        val dataVirtualRequest = Output(Valid(new DataRequest))
        val fetchPhysicalCheck = Output(Valid(new GuestPhysicalAccess))
        val dataPhysicalCheck = Output(Valid(new GuestPhysicalAccess))
        // Valid event probes below mean accepted, not merely offered.
        val fpStart = Output(Valid(new SystemRequest(p)))
        val fpComplete = Output(Valid(new BackendCompletion(p)))
        val fpRetire = Output(Valid(new RobToken(p)))
        val fpStartOffered = Output(Bool())
        val fpStartReady = Output(Bool())
        val systemStartReady = Output(Bool())
        val fpCompleteOffered = Output(Bool())
        val systemStart = Output(Valid(new SystemRequest(p)))
        val systemComplete = Output(Valid(new SystemResult(p)))
        val systemExecute = Output(Bool())
        val systemRequest = Output(new SystemRequest(p))
        val hWrite = Output(Valid(new GuestInterruptCsrWrite))
        val fpCsrWrite = Output(Valid(new FloatingPointCsr))
        val hostFsWrite = Output(Valid(UInt(2.W)))
        val mutation = Output(Valid(new FloatingPointMutation))
        val ownerActive = Output(Bool())
        val ownerToken = Output(new RobToken(p))
        val contextMemoryEpoch = Output(Bool())
        val hMemoryEpoch = Output(Bool())
        val fpMemoryEpoch = Output(Bool())
        val retireMatches = Output(UInt(2.W))
        val statePhase = Output(UInt(2.W))
        val systemState = Output(UInt(4.W))
        val fpBusy = Output(Bool())
        val trapReady = Output(Bool())
        val pendingException = Output(Valid(new HeadException(p)))
        val recovering = Output(Bool())
        val memoryBusy = Output(Bool())
        val fpMemoryBusy = Output(Bool())
        val adapterIdle = Output(Bool())
        val translatorIdle = Output(Bool())
        val fetchAdapterIdle = Output(Bool())
        val fetchTranslatorIdle = Output(Bool())
        val assemblerIdle = Output(Bool())
        val responseBufferIdle = Output(Bool())
        val completionCount = Output(UInt(2.W))
        val memoryDrained = Output(Bool())
        val hostFs = Output(UInt(2.W))
        val guestFs = Output(UInt(2.W))
        val hostSd = Output(Bool())
        val guestSd = Output(Bool())
        val fcsr = Output(UInt(8.W))
        val hstatus = Output(UInt(64.W))
        val htval = Output(UInt(64.W))
        val htinst = Output(UInt(64.W))
        val scause = Output(UInt(64.W))
        val sepc = Output(UInt(64.W))
        val stval = Output(UInt(64.W))
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
    val core = Module(new HypervisorMachineCore(guardedGuestFpQualification = !(arithmetic || multiply),
        guardedGuestFpArithmeticQualification = arithmetic, guardedGuestFpMultiplyQualification = multiply))
    core.io.enable := io.enable
    core.io.commitEnable := io.commitEnable
    io.instruction <> core.io.instruction
    io.data <> core.io.data
    io.fetchPte <> core.io.fetchPte
    io.dataPte <> core.io.dataPte
    io.commit0 := core.io.commit0
    io.commit1 := core.io.commit1
    io.trap := core.io.trap
    io.fetchPc := core.io.fetchPc
    io.virtualized := core.io.virtualized
    io.dataVirtualRequest := core.io.dataVirtualRequest
    io.fetchPhysicalCheck := core.io.fetchPhysicalCheck
    io.dataPhysicalCheck := core.io.dataPhysicalCheck
    def ram(address: UInt): Bool = address >= "h80000000".U && address < "h81000000".U
    core.io.dataPmaDenied := !ram(core.io.dataPhysicalCheck.bits.address)
    core.io.fetchPmaDenied := !ram(core.io.fetchPhysicalCheck.bits.address)
    core.io.dataPmaUncached := false.B
    core.io.timerInterrupt := false.B
    core.io.timeValue := 0.U
    core.io.msi.request.valid := false.B
    core.io.msi.request.bits := 0.U.asTypeOf(core.io.msi.request.bits)
    core.io.msi.response.ready := true.B

    // Bores are observation-only sinks. No probe is connected back to the core.
    val backend = core.core.core.backend
    val system = backend.systemUnit.get
    val fp = system.floatingPoint.get
    val hypervisor = system.hypervisor.get
    val owner = backend.protectedSystem
    val memory = fp.memoryOption.get
    io.privilege := BoringUtils.bore(system.privilege)
    io.fpStartOffered := BoringUtils.bore(fp.io.start.valid)
    io.fpStartReady := BoringUtils.bore(fp.io.start.ready)
    io.systemStartReady := BoringUtils.bore(system.io.start.ready)
    io.fpStart.valid := io.fpStartOffered && BoringUtils.bore(fp.io.start.ready)
    io.fpStart.bits := BoringUtils.bore(fp.io.start.bits)
    io.fpCompleteOffered := BoringUtils.bore(fp.io.complete.valid)
    io.fpComplete.valid := io.fpCompleteOffered && BoringUtils.bore(fp.io.complete.ready)
    io.fpComplete.bits := BoringUtils.bore(fp.io.complete.bits)
    io.fpRetire.valid := BoringUtils.bore(fp.fp.io.retireAccepted)
    io.fpRetire.bits := BoringUtils.bore(fp.io.retire.bits)
    io.systemStart.valid := BoringUtils.bore(system.io.start.valid) && BoringUtils.bore(system.io.start.ready)
    io.systemStart.bits := BoringUtils.bore(system.io.start.bits)
    io.systemComplete.valid := BoringUtils.bore(system.io.complete.valid) && BoringUtils.bore(system.io.complete.ready)
    io.systemComplete.bits := BoringUtils.bore(system.io.complete.bits)
    io.systemRequest := BoringUtils.bore(system.request)
    io.systemState := BoringUtils.bore(system.state)
    io.systemExecute := io.systemState === system.execute
    io.hWrite := BoringUtils.bore(hypervisor.io.write)
    io.fpCsrWrite.bits := BoringUtils.bore(fp.io.csr.bits)
    io.fpCsrWrite.valid := BoringUtils.bore(fp.io.csr.valid) && BoringUtils.bore(fp.io.csr.ready) &&
        io.fpCsrWrite.bits.write
    io.hostFsWrite.valid := BoringUtils.bore(fp.io.setFs.valid) && BoringUtils.bore(fp.io.setFs.ready)
    io.hostFsWrite.bits := BoringUtils.bore(fp.io.setFs.bits)
    io.mutation := BoringUtils.bore(fp.io.mutation.get)
    io.ownerActive := BoringUtils.bore(owner.io.active)
    io.ownerToken := BoringUtils.bore(owner.io.token)
    io.contextMemoryEpoch := BoringUtils.bore(owner.io.contextMemoryEpoch)
    io.hMemoryEpoch := BoringUtils.bore(owner.io.hMemoryEpoch)
    io.fpMemoryEpoch := BoringUtils.bore(owner.io.fpMemoryEpoch)
    io.retireMatches := BoringUtils.bore(owner.io.retireMatches).asUInt
    io.statePhase := BoringUtils.bore(fp.fp.state)
    io.fpBusy := BoringUtils.bore(fp.io.busy)
    io.trapReady := BoringUtils.bore(system.io.trapReady)
    io.pendingException := BoringUtils.bore(backend.ledger.io.pendingException)
    io.recovering := BoringUtils.bore(backend.ledger.io.recovering)
    io.memoryBusy := BoringUtils.bore(backend.io.memoryBusy)
    io.fpMemoryBusy := BoringUtils.bore(fp.io.memoryBusy)
    io.adapterIdle := BoringUtils.bore(core.data.io.idle)
    io.translatorIdle := BoringUtils.bore(core.dw.io.idle)
    io.fetchAdapterIdle := BoringUtils.bore(core.fetch.io.idle)
    io.fetchTranslatorIdle := BoringUtils.bore(core.fw.io.idle)
    io.assemblerIdle := BoringUtils.bore(core.assemble.io.idle)
    io.responseBufferIdle := BoringUtils.bore(memory.responses.io.idle)
    io.completionCount := BoringUtils.bore(memory.completions.io.count)
    // Data-side drain includes the real downstream adapter/walker, not FP architectural busy.
    io.memoryDrained := !io.memoryBusy && io.adapterIdle && io.translatorIdle &&
        io.responseBufferIdle && io.completionCount === 0.U
    io.hostFs := BoringUtils.bore(fp.io.fs)
    io.guestFs := BoringUtils.bore(hypervisor.io.floatingPoint.get.fs)
    io.hostSd := io.hostFs === 3.U
    io.guestSd := BoringUtils.bore(hypervisor.io.floatingPoint.get.sd)
    io.fcsr := BoringUtils.bore(fp.io.fcsr)
    io.hstatus := BoringUtils.bore(hypervisor.hstatus)
    io.htval := BoringUtils.bore(hypervisor.htval)
    io.htinst := BoringUtils.bore(hypervisor.htinst)
    io.scause := BoringUtils.bore(system.scause)
    io.sepc := BoringUtils.bore(system.sepc)
    io.stval := BoringUtils.bore(system.stval)
    // Includes the existing committed bank's queued physical write, never speculative data.
    val architectural = BoringUtils.bore(fp.fp.architecturalRegisters)
    for (index <- 0 until 32) io.elements(s"fpr_$index").asInstanceOf[UInt] := architectural(index)
}

object GuardedGuestFpCoreGsimMain extends App {
    require(args.length == 1, "output-directory")
    ChiselStage.emitCHIRRTLFile(new GuardedGuestFpCoreGsim, Array("--target-dir", args.head))
}
