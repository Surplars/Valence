package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.interrupt.ImsicParams
import soc.ip.memory.NativeMemoryPort

/** Conservative real OoO+H integration: scalar fetch, two independent uncached
  * nested walkers, and a drained single-owner data adapter. Default production
  * MachinePlatform is unchanged and misa.H remains clear. The integration owns
  * PMA: fetchPhysicalCheck requires executable side-effect-free memory; data
  * checking uses SPA and forceExecute, with classification captured before the
  * offer. Both PTE ports must connect only to a side-effect-free physical read
  * endpoint that rejects non-memory PMA. No TLB or cache is instantiated here.
  */
class HypervisorMachineCore(platformIntegration: Boolean = false) extends Module {
    val p = OooParams(hypervisorExperiment = true, robEntries = 16, physicalRegs = 48,
        memoryEntries = 2, compressedInstructions = true, machineSystem = true, virtualMemoryLevels = 3, pmpEntries = 16)
    val io = IO(new Bundle {
        // The default standalone shape remains unchanged. Platform FENCE.I waits for shared drain.
        val platformFence = if (platformIntegration) Some(Output(Bool())) else None
        val platformFenceReady = if (platformIntegration) Some(Input(Bool())) else None
        val privateOwnersIdle = if (platformIntegration) Some(Output(Bool())) else None
        val enable = Input(Bool())
        val commitEnable = Input(Bool())
        val commit0 = Output(Valid(new CommitRecord(p)))
        val commit1 = Output(Valid(new CommitRecord(p)))
        val trap = Output(Valid(new HeadException(p)))
        val fetchPc = Output(UInt(64.W))
        val virtualized = Output(Bool())
        val instruction = new GuestScalarFetchPort(2)
        val data = new NativeMemoryPort
        val fetchPte = new SvPteReadPort
        val dataPte = new SvPteReadPort
        val dataVirtualRequest = Output(Valid(new DataRequest))
        val msi = Flipped(new soc.ip.bus.RegisterPort)
        val timerInterrupt = Input(Bool())
        val timeValue = Input(UInt(64.W))
        val fetchPhysicalCheck = Output(Valid(new GuestPhysicalAccess))
        val dataPhysicalCheck = Output(Valid(new GuestPhysicalAccess))
        val fetchPmaDenied = Input(Bool())
        val dataPmaDenied = Input(Bool())
        val dataPmaUncached = Input(Bool())
    })
    val core = Module(new MachineCore(p, ImsicParams(guestFiles = 3), experimentalHypervisor = true))
    val fetch = Module(new GuestFetchTranslationAdapter(2))
    val assemble = Module(new GuestInstructionAssembler)
    val data = Module(new GuestDataTranslationAdapter())
    val fw = Module(new GuestTranslationService(p.pmpEntries))
    val dw = Module(new GuestTranslationService(p.pmpEntries))
    fw.io.request <> fetch.io.translation.request; fetch.io.translation.response <> fw.io.response
    dw.io.request <> data.io.translation.request; data.io.translation.response <> dw.io.response
    fw.io.cancel := fetch.io.translationCancel; dw.io.cancel := data.io.translationCancel
    fw.io.pmpState := core.io.pmpState.get; dw.io.pmpState := core.io.pmpState.get
    io.fetchPte <> fw.io.memory; io.dataPte <> dw.io.memory
    io.instruction <> fetch.io.physical; io.data <> data.io.physical
    data.io.virtual <> core.io.memory
    data.io.context := core.io.guestDataContext.get
    data.io.cancel := false.B // The existing LSU retains/drains cancelled owners.
    core.io.guestDataFault.get := data.io.guestFault
    io.dataPhysicalCheck := data.io.physicalCheck
    io.fetchPhysicalCheck := fetch.io.physicalCheck
    data.io.pmaDenied := io.dataPmaDenied
    fetch.io.pmaDenied := io.fetchPmaDenied
    val physicalUncached = RegEnable(io.dataPmaUncached, data.io.physicalCheck.valid)
    io.data.request.bits.uncached := physicalUncached
    assemble.io.parcel <> fetch.io.virtual
    fetch.io.context := assemble.io.parcelContext
    fetch.io.cancel := assemble.io.parcelCancel
    assemble.io.parcelGuestFault := fetch.io.guestFault
    assemble.io.parcelCancelled := fetch.io.cancelled
    assemble.io.parcelResponseEpoch := fetch.io.responseEpoch
    assemble.io.parcelResponseAddress := fetch.io.responseAddress
    val outstanding = RegInit(false.B)
    val ownerPc = Reg(UInt(64.W))
    val ownerContext = Reg(new GuestTranslationRequest)
    val changed = outstanding && (ownerPc =/= core.io.fetchPc ||
        ownerContext.asUInt =/= core.io.guestFetchContext.get.asUInt)
    val discard = changed || core.io.pauseFetch.get || !io.enable
    assemble.io.cancel := discard
    assemble.io.request.valid := io.enable && !outstanding && !core.io.pauseFetch.get
    assemble.io.request.bits.pc := core.io.fetchPc
    assemble.io.request.bits.context := core.io.guestFetchContext.get
    val nextOwner = RegInit(0.U(64.W))
    assemble.io.request.bits.owner := nextOwner
    when(assemble.io.request.fire) {
        nextOwner := nextOwner + 1.U
        outstanding := true.B; ownerPc := core.io.fetchPc; ownerContext := core.io.guestFetchContext.get
    }
    val supply = assemble.io.response.valid && !assemble.io.response.bits.cancelled && !discard
    core.io.instructions := 0.U.asTypeOf(core.io.instructions)
    core.io.instructionFaults := 0.U.asTypeOf(core.io.instructionFaults)
    core.io.instructionPageFaults := 0.U.asTypeOf(core.io.instructionPageFaults)
    core.io.guestInstructionFault.get := 0.U.asTypeOf(core.io.guestInstructionFault.get)
    core.io.instructions(0).valid := supply
    core.io.instructions(0).bits := assemble.io.response.bits.instruction
    core.io.instructionFaults(0) := assemble.io.response.bits.error
    core.io.instructionPageFaults(0) := assemble.io.response.bits.pageFault
    core.io.guestInstructionFault.get(0) := assemble.io.response.bits.guestFault
    core.io.instructionFaultAddresses.get := VecInit(Seq.fill(p.renameWidth)(assemble.io.response.bits.faultAddress))
    assemble.io.response.ready := core.io.accepted(0) || discard || assemble.io.response.bits.cancelled
    when(assemble.io.response.fire) { outstanding := false.B }
    when(supply) {
        assert(assemble.io.response.bits.pc === core.io.fetchPc && assemble.io.response.bits.epoch === ownerContext.epoch &&
            assemble.io.response.bits.owner === nextOwner - 1.U,
            "only the current scalar fetch owner may enter the ROB")
    }
    core.io.fetchQuiescent.get := assemble.io.idle && fetch.io.idle && fw.io.idle
    core.io.vmFlushReady.get := assemble.io.idle && fetch.io.idle && fw.io.idle && data.io.idle && dw.io.idle
    val privateIdle = assemble.io.idle && fetch.io.idle && fw.io.idle && data.io.idle && dw.io.idle
    io.privateOwnersIdle.foreach(_ := privateIdle)
    io.platformFence.foreach(_ := core.io.fenceIFlush)
    core.io.fenceIFlushReady := assemble.io.idle && fetch.io.idle && fw.io.idle &&
        io.platformFenceReady.getOrElse(true.B)
    core.io.timerInterrupt := io.timerInterrupt; core.io.timeValue := io.timeValue
    core.io.commitEnable := io.enable && io.commitEnable
    core.io.inspectRegister := 0.U
    core.io.msi <> io.msi
    io.commit0 := core.io.commit(0); io.commit1 := core.io.commit(1); io.trap := core.io.trap
    io.fetchPc := core.io.fetchPc; io.virtualized := core.io.virtualized.get
    io.dataVirtualRequest.valid := core.io.memory.request.fire
    io.dataVirtualRequest.bits := core.io.memory.request.bits
}