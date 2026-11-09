package soc.integration.spinor

import chisel3._
import chisel3.util._
import soc.core.inorder._
import soc.ip.bus.{CdcMailbox, CdcResetRelease}
import vpu._

/** FCSR travels with the command, never as an independently synchronized bus. */
class I1SpinorCommandSnapshot extends Bundle {
    val command = new I1SpinorCommand
    val frm = UInt(3.W)
    val fflags = UInt(5.W)
}

/** Capacity-one asynchronous transactions between CPU and Spinor clocks.
  * A mailbox owns each accepted packet until its destination consumes it.
  * CPU retains instruction ownership through done; preview is consumed only
  * when the CPU accepts its grant. No stop/context or unilateral reset exists
  * in this first binding. All domains and memory use a common cold-reset epoch.
  * Held-data/toggle crossings still need scoped physical CDC constraints.
  */
class I1SpinorClockBoundary extends RawModule {
    val cpuClock = IO(Input(Clock()))
    val vpuClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val cpu = IO(Flipped(new I1SpinorPort))
    val native = IO(new I1SpinorPort)
    val vpuMemory = IO(Flipped(new VpuTileLinkMaster(VpuTLParams())))
    val cpuMemory = IO(new VpuTileLinkMaster(VpuTLParams()))
    // Local transport drain observations, not whole-system CMU permission.
    val cpuTransportIdle = IO(Output(Bool()))
    val vpuTransportIdle = IO(Output(Bool()))

    private def channel(width: Int, fromCpu: Boolean): CdcMailbox = {
        val box = Module(new CdcMailbox(width))
        box.sourceClock := (if (fromCpu) cpuClock else vpuClock)
        box.destinationClock := (if (fromCpu) vpuClock else cpuClock)
        box.commonReset := commonColdReset
        box
    }
    val commandBox = channel((new I1SpinorCommandSnapshot).getWidth, fromCpu = true)
    val previewBox = channel((new I1SpinorResult).getWidth, fromCpu = false)
    val grantBox = channel(80, fromCpu = true)
    val doneBox = channel((new I1SpinorResult).getWidth, fromCpu = false)
    val memoryRequestBox = channel((new VpuTLA(VpuTLParams())).getWidth, fromCpu = false)
    val memoryResponseBox = channel((new VpuTLD(VpuTLParams())).getWidth, fromCpu = true)

    val snapshot = Wire(new I1SpinorCommandSnapshot)
    snapshot.command := cpu.command.bits; snapshot.frm := cpu.frm; snapshot.fflags := cpu.fflags
    commandBox.source.valid := cpu.command.valid
    commandBox.source.bits := snapshot.asUInt; cpu.command.ready := commandBox.source.ready
    val received = commandBox.destination.bits.asTypeOf(new I1SpinorCommandSnapshot)
    native.command.valid := commandBox.destination.valid
    native.command.bits := received.command; commandBox.destination.ready := native.command.ready

    private val cpuRelease = Module(new CdcResetRelease)
    cpuRelease.clockIn := cpuClock; cpuRelease.asyncReset := commonColdReset
    private val vpuRelease = Module(new CdcResetRelease)
    vpuRelease.clockIn := vpuClock; vpuRelease.asyncReset := commonColdReset
    private val cpuOwned = withClockAndReset(cpuClock, cpuRelease.resetOut) { RegInit(false.B) }
    private val vpuOwned = withClockAndReset(vpuClock, vpuRelease.resetOut) { RegInit(false.B) }
    private val previewSent = withClockAndReset(vpuClock, vpuRelease.resetOut) { RegInit(false.B) }
    private val frm = withClockAndReset(vpuClock, vpuRelease.resetOut) { RegInit(0.U(3.W)) }
    private val fflags = withClockAndReset(vpuClock, vpuRelease.resetOut) { RegInit(0.U(5.W)) }
    // Spinor samples frm on this offer edge; present the new atomic snapshot
    // before the edge, then retain it throughout execution and publication.
    native.frm := Mux(native.command.valid, received.frm, frm)
    native.fflags := Mux(native.command.valid, received.fflags, fflags)
    withClockAndReset(vpuClock, vpuRelease.resetOut) {
        when(native.command.fire) { frm := received.frm; fflags := received.fflags; vpuOwned := true.B }
        when(previewBox.source.fire) { previewSent := true.B }
        when(native.done.fire) { previewSent := false.B; vpuOwned := false.B }
    }
    previewBox.source.valid := native.preview.valid && !previewSent
    previewBox.source.bits := native.preview.bits.asUInt
    cpu.preview.valid := previewBox.destination.valid
    cpu.preview.bits := previewBox.destination.bits.asTypeOf(new I1SpinorResult)
    previewBox.destination.ready := cpu.grant.fire
    grantBox.source.valid := cpu.grant.valid
    grantBox.source.bits := cpu.grant.bits; cpu.grant.ready := grantBox.source.ready
    native.grant.valid := grantBox.destination.valid
    native.grant.bits := grantBox.destination.bits; grantBox.destination.ready := native.grant.ready
    doneBox.source.valid := native.done.valid
    doneBox.source.bits := native.done.bits.asUInt; native.done.ready := doneBox.source.ready
    cpu.done.valid := doneBox.destination.valid
    cpu.done.bits := doneBox.destination.bits.asTypeOf(new I1SpinorResult)
    doneBox.destination.ready := cpu.done.ready
    withClockAndReset(cpuClock, cpuRelease.resetOut) {
        when(cpu.command.fire) { cpuOwned := true.B }
        when(cpu.done.fire) { cpuOwned := false.B }
        when(cpu.grant.fire) {
            assert(cpu.preview.valid && cpu.grant.bits === cpu.preview.bits.token,
                "CPU grant must consume its retained preview")
        }
    }
    memoryRequestBox.source.valid := vpuMemory.a.valid
    memoryRequestBox.source.bits := vpuMemory.a.bits.asUInt; vpuMemory.a.ready := memoryRequestBox.source.ready
    cpuMemory.a.valid := memoryRequestBox.destination.valid
    cpuMemory.a.bits := memoryRequestBox.destination.bits.asTypeOf(new VpuTLA(VpuTLParams()))
    memoryRequestBox.destination.ready := cpuMemory.a.ready
    memoryResponseBox.source.valid := cpuMemory.d.valid
    memoryResponseBox.source.bits := cpuMemory.d.bits.asUInt; cpuMemory.d.ready := memoryResponseBox.source.ready
    vpuMemory.d.valid := memoryResponseBox.destination.valid
    vpuMemory.d.bits := memoryResponseBox.destination.bits.asTypeOf(new VpuTLD(VpuTLParams()))
    memoryResponseBox.destination.ready := vpuMemory.d.ready

    cpuTransportIdle := !cpuOwned && commandBox.sourceIdle && previewBox.destinationIdle &&
        grantBox.sourceIdle && doneBox.destinationIdle &&
        memoryRequestBox.destinationIdle && memoryResponseBox.sourceIdle
    vpuTransportIdle := !vpuOwned && commandBox.destinationIdle && previewBox.sourceIdle &&
        grantBox.destinationIdle && doneBox.sourceIdle &&
        memoryRequestBox.sourceIdle && memoryResponseBox.destinationIdle
}
