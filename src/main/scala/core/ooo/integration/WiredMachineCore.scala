package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.bus.RegisterPort
import soc.ip.interrupt.{Aplic, AplicParams, ImsicParams}

/** Reusable assembly with external APLIC control/data/instruction boundaries; not a complete bus-connected SoC. */
class WiredMachineCore(
    p: OooParams = OooParams(),
    imsicParams: ImsicParams = ImsicParams(),
    aplicParams: AplicParams = AplicParams()
) extends Module {
    require(aplicParams.msiBase == imsicParams.machineBase && aplicParams.identities == imsicParams.identities)
    require(p.virtualMemoryLevels == 0, "wired wrapper has no translation flush boundary")
    val io = IO(new Bundle {
        val timerInterrupt   = Input(Bool())
        val timeValue        = Input(UInt(64.W))
        val instructions     = Input(Vec(p.renameWidth, Valid(UInt(32.W))))
        val instructionFaults = Input(Vec(p.renameWidth, Bool()))
        val instructionPageFaults = Input(Vec(p.renameWidth, Bool()))
        val instructionFaultAddresses = if (p.compressedInstructions)
            Some(Input(Vec(p.renameWidth, UInt(64.W)))) else None
        val accepted         = Output(Vec(p.renameWidth, Bool()))
        val fetchPc          = Output(UInt(64.W))
        val commitEnable     = Input(Bool())
        val commit           = Output(Vec(p.commitWidth, Valid(new CommitRecord(p))))
        val trap             = Output(Valid(new HeadException(p)))
        val redirect         = Output(Valid(new FrontendRedirect(p)))
        val invalidateFetch  = Output(Bool())
        val recovering       = Output(Bool())
        val memory           = new DataPort
        val interruptControl = Flipped(new RegisterPort)
        val sources          = Input(UInt(aplicParams.sources.W))
        val msiError         = Output(Bool())
        val externalPending  = Output(UInt(imsicParams.files.W))
        val inspectRegister  = Input(UInt(5.W))
        val committedValue   = Output(UInt(64.W))
    })
    val core  = Module(new MachineCore(p, imsicParams))
    val aplic = Module(new Aplic(aplicParams))
    core.io.msi <> aplic.io.msi
    aplic.io.mmio <> io.interruptControl
    aplic.io.sources        := io.sources
    io.msiError             := aplic.io.msiError
    core.io.timerInterrupt  := io.timerInterrupt
    core.io.timeValue       := io.timeValue
    core.io.fenceIFlushReady := true.B
    core.io.instructions    := io.instructions
    core.io.instructionFaults := io.instructionFaults
    core.io.instructionPageFaults := io.instructionPageFaults
    core.io.instructionFaultAddresses.foreach(_ := io.instructionFaultAddresses.get)
    core.io.commitEnable    := io.commitEnable
    core.io.inspectRegister := io.inspectRegister
    io.memory <> core.io.memory
    io.accepted        := core.io.accepted
    io.fetchPc         := core.io.fetchPc
    io.commit          := core.io.commit
    io.trap            := core.io.trap
    io.redirect        := core.io.redirect
    io.invalidateFetch := core.io.invalidateFetch
    io.recovering      := core.io.recovering
    io.externalPending := core.io.externalPending
    io.committedValue  := core.io.committedValue
}
