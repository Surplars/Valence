package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.bus.RegisterPort
import soc.ip.interrupt.{Imsic, ImsicParams}

/** Initial system-capable assembly: CPU + independent IMSIC, with external instruction/data/MSI boundaries. The M/S
  * IMSIC files and external interrupt signals are connected; VS delivery remains future work.
  */
class MachineCore(p: OooParams = OooParams(), imsicParams: ImsicParams = ImsicParams()) extends Module {
    val io = IO(new Bundle {
        val timerInterrupt  = Input(Bool())
        val timeValue       = Input(UInt(64.W))
        val instructions    = Input(Vec(p.renameWidth, Valid(UInt(32.W))))
        val instructionFaults = Input(Vec(p.renameWidth, Bool()))
        val instructionPageFaults = Input(Vec(p.renameWidth, Bool()))
        val instructionFaultAddresses = if (p.compressedInstructions)
            Some(Input(Vec(p.renameWidth, UInt(64.W)))) else None
        val accepted        = Output(Vec(p.renameWidth, Bool()))
        val fetchPc         = Output(UInt(64.W))
        val pmpState        = if (p.pmpEntries > 0) Some(Output(new PmpState)) else None
        val fetchPrivilege  = if (p.pmpEntries > 0) Some(Output(UInt(2.W))) else None
        val fetchQuiescent  = if (p.pmpEntries > 0) Some(Input(Bool())) else None
        val pauseFetch      = if (p.pmpEntries > 0) Some(Output(Bool())) else None
        val vmState         = if (p.virtualMemoryLevels > 0) Some(Output(new VmCsrState)) else None
        val vmFlush         = if (p.virtualMemoryLevels > 0) Some(Output(Bool())) else None
        val vmFlushReady    = if (p.virtualMemoryLevels > 0) Some(Input(Bool())) else None
        val commitEnable    = Input(Bool())
        val commit          = Output(Vec(p.commitWidth, Valid(new CommitRecord(p))))
        val trap            = Output(Valid(new HeadException(p)))
        val redirect        = Output(Valid(new FrontendRedirect(p)))
        val invalidateFetch = Output(Bool())
        val fenceIFlush     = Output(Bool())
        val fenceIFlushReady = Input(Bool())
        val recovering      = Output(Bool())
        val memory          = new DataPort
        val loadPrecheck = if (p.virtualRamLoadPrecheck) Some(new VirtualLoadPrecheckPort) else None
        val msi             = Flipped(new RegisterPort)
        val externalPending = Output(UInt(imsicParams.files.W))
        val inspectRegister = Input(UInt(5.W))
        val committedValue  = Output(UInt(64.W))
        val robOccupancy    = Output(UInt(p.countBits.W))
        val headProfile     = Output(new HeadProfile)
        val issueCount      = Output(UInt(log2Ceil(p.issueWidth + 1).W))
        val externalPrefetchBusy = if (p.dataNextLinePrefetch) Some(Input(Bool())) else None
        val memoryBusy      = Output(Bool())
    })
    val core  = Module(new IntegerCore(p.copy(machineSystem = true)))
    val imsic = Module(new Imsic(imsicParams))
    core.io.imsic.get.request <> imsic.io.csrRequest
    core.io.imsic.get.response <> imsic.io.csrResponse
    imsic.io.mmio <> io.msi
    // The board profile cuts the routed IMSIC -> recovery-ledger critical path.
    // A pending level is delayed by one cycle, while CSR reads remain direct.
    val irqLevels = if (p.registeredImsicInterrupts)
        RegNext(imsic.io.interrupts, 0.U(imsicParams.files.W)) else imsic.io.interrupts
    core.io.externalInterrupt.get           := irqLevels(0)
    core.io.supervisorExternalInterrupt.get := irqLevels(1)
    io.externalPending                      := imsic.io.interrupts
    core.io.timerInterrupt.get              := io.timerInterrupt
    core.io.timeValue.get                   := io.timeValue
    io.fenceIFlush := core.io.fenceIFlush.get
    core.io.fenceIFlushReady.get := io.fenceIFlushReady
    core.io.instructions                    := io.instructions
    core.io.instructionFaults               := io.instructionFaults
    core.io.instructionPageFaults           := io.instructionPageFaults
    core.io.instructionFaultAddresses.foreach(_ := io.instructionFaultAddresses.get)
    if (p.pmpEntries > 0) {
        io.pmpState.get := core.io.pmpState.get
        io.fetchPrivilege.get := core.io.fetchPrivilege.get
        core.io.fetchQuiescent.get := io.fetchQuiescent.get
        io.pauseFetch.get := core.io.pauseFetch.get
    }
    if (p.virtualMemoryLevels > 0) {
        io.vmState.get := core.io.vmState.get
        io.vmFlush.get := core.io.vmFlush.get
        core.io.vmFlushReady.get := io.vmFlushReady.get
    }
    core.io.commitEnable                    := io.commitEnable
    core.io.inspectRegister                 := io.inspectRegister
    io.loadPrecheck.foreach(_ <> core.io.loadPrecheck.get)
    io.memory <> core.io.memory
    io.accepted       := core.io.accepted
    io.fetchPc        := core.io.fetchPc
    io.commit         := core.io.commit
    io.trap           := core.io.trap.get
    io.redirect       := core.io.redirect
    io.invalidateFetch := core.io.invalidateFetch
    io.recovering     := core.io.recovering
    io.committedValue := core.io.committedValue
    io.robOccupancy := core.io.occupancy
    io.headProfile := core.io.headProfile
    io.issueCount := core.io.issueCount
    if (p.dataNextLinePrefetch) core.io.externalPrefetchBusy.get := io.externalPrefetchBusy.get
    io.memoryBusy := core.io.memoryBusy
}
