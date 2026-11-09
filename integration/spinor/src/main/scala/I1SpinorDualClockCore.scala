package soc.integration.spinor

import chisel3._
import chisel3.util._
import soc.core.inorder._
import soc.ip.bus.{CdcLevel, CdcResetRelease, ResetDistributionDriver}
import vpu._

/** Opt-in physical-memory CPU/Spinor composition with independent clocks.
  * VPU target is 300 MHz; clocks come from the platform, not this module.
  * No SoC fabric, CMU, clock gating, warm reset or vector MMU is instantiated.
  * Function/CDC/physical qualification of this dual-clock top is separate
  * from the existing same-clock instruction checks and frozen VPU results.
  */
class I1SpinorDualClockCore(val p: FiveStageConfig, managedClocks: Boolean = false) extends RawModule {
    require(p.spinor)
    val cpuClock = IO(Input(Clock()))
    val vpuClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val io = IO(new Bundle {
        val instructionMemory = new FiveStageBurstPort(p)
        val dataMemory = new FiveStageBurstPort(p)
        val time = Input(UInt(64.W))
        val externalIrq = Input(Bool()); val timerIrq = Input(Bool()); val softwareIrq = Input(Bool())
        val retire = Valid(new FiveStageRetire(p))
        val protocolError = Output(Bool())
        val cpuTransportIdle = Output(Bool())
        val vpuTransportIdle = Output(Bool())
        val supervisorExternalIrq = if (p.withSupervisor) Some(Input(Bool())) else None
        // CPU-clock signals except vectorIdle, which belongs to VPU clock.
        val quiesceRequest = if (managedClocks) Some(Input(Bool())) else None
        val blockVectorAdmission = if (managedClocks) Some(Input(Bool())) else None
        val cpuQuiescent = if (managedClocks) Some(Output(Bool())) else None
        val vectorIdle = if (managedClocks) Some(Output(Bool())) else None
        val vectorWake = if (managedClocks) Some(Output(Bool())) else None
    })
    // Two synchronization stages plus one local distribution edge preserve
    // the original three-edge cold release. Only the first two stages resolve
    // metastability; the ordinary final driver can serve the CPU reset fanout.
    val cpuRelease = Module(new CdcResetRelease(syncStages = 2))
    cpuRelease.clockIn := cpuClock; cpuRelease.asyncReset := commonColdReset
    val cpuResetDriver = Module(new ResetDistributionDriver)
    cpuResetDriver.clockIn := cpuClock; cpuResetDriver.synchronizedReset := cpuRelease.resetOut
    val vpuRelease = Module(new CdcResetRelease)
    vpuRelease.clockIn := vpuClock; vpuRelease.asyncReset := commonColdReset
    // Preserve synchronous reset at the original CPU/VPU module interfaces.
    // Each domain receives an independently synchronized cold-reset release.
    val cpu = withClockAndReset(cpuClock, cpuResetDriver.resetOut.asBool) {
        Module(new FiveStageCachedCore(p, externalQuiesce = managedClocks, reportQuiescence = managedClocks))
    }
    val vector = withClockAndReset(vpuClock, vpuRelease.resetOut.asBool) {
        // With H, virtual addresses span XLEN. The CPU performs VS/G/PMP
        // checks and rejects translated vector accesses outside normal RAM.
        val config = if (p.withH) SpinorParams(hostFcsr = true, regionBase = 0,
            regionBytes = BigInt(1) << 64) else SpinorParams(hostFcsr = true)
        Module(new SpinorIsolated(config = config))
    }
    val memory = withClockAndReset(cpuClock, cpuResetDriver.resetOut.asBool) {
        Module(new I1SpinorMemoryBridge(p))
    }
    val boundary = Module(new I1SpinorClockBoundary)
    boundary.cpuClock := cpuClock; boundary.vpuClock := vpuClock; boundary.commonColdReset := commonColdReset
    boundary.cpu <> cpu.io.spinor.get
    if (managedClocks) {
        // Only new command admission stops. Accepted commands, authorization,
        // completion and all memory beats continue to drain their real owners.
        val command = cpu.io.spinor.get.command
        boundary.cpu.command.valid := command.valid && !io.blockVectorAdmission.get
        command.ready := boundary.cpu.command.ready && !io.blockVectorAdmission.get
        cpu.io.quiesceRequest.get := io.quiesceRequest.get
        io.cpuQuiescent.get := cpu.io.architecturalStopped.get && cpu.io.privateCachesQuiescent.get
        io.vectorIdle.get := !vector.io.busy
        io.vectorWake.get := command.valid
    }
    memory.io.tl <> boundary.cpuMemory; boundary.vpuMemory <> vector.io.tl
    cpu.io.spinorMemory.get <> memory.io.memory
    if (p.withH) {
        memory.io.begin.get.valid := cpu.io.spinor.get.command.fire
        memory.io.begin.get.bits := cpu.io.spinor.get.command.bits.token
        cpu.io.spinorMemoryFault.get := memory.io.fault.get
    }
    val host = boundary.native
    vector.io.offer.valid := host.command.valid; host.command.ready := vector.io.offer.ready
    vector.io.offer.bits.instruction := host.command.bits.instruction
    vector.io.offer.bits.scalar := host.command.bits.scalar
    vector.io.offer.bits.scalar2 := host.command.bits.scalar2
    vector.io.offer.bits.avl := host.command.bits.avl
    vector.io.offer.bits.token := host.command.bits.token
    vector.io.grant <> host.grant
    private def result(out: I1SpinorResult, in: IsolatedResult): Unit = {
        out.token := in.reply.completion.token; out.instruction := in.reply.completion.instruction
        out.scalar := in.reply.completion.scalar; out.writesScalar := in.reply.completion.writesScalar
        out.illegal := in.reply.completion.illegal; out.exception := in.reply.exception
        out.cause := in.reply.cause; out.tval := in.reply.tval
        out.flagsValid := in.flagsValid; out.flags := in.flags
    }
    host.preview.valid := vector.io.preview.valid; result(host.preview.bits, vector.io.preview.bits)
    host.done.valid := vector.io.done.valid; result(host.done.bits, vector.io.done.bits.result)
    vector.io.done.ready := host.done.ready
    vector.io.fcsrHost.get.frm := host.frm; vector.io.fcsrHost.get.fflags := host.fflags
    vector.io.stop := false.B; vector.io.contextMode := false.B
    vector.io.context.valid := false.B; vector.io.context.bits := 0.U.asTypeOf(new ContextAccess)
    vector.io.contextResult.ready := true.B
    vector.io.monitor.a.valid := false.B
    vector.io.monitor.a.bits := 0.U.asTypeOf(new VpuTLA(VpuTLParams()))
    vector.io.monitor.d.ready := true.B
    io.instructionMemory <> cpu.io.instructionMemory; io.dataMemory <> cpu.io.dataMemory
    cpu.io.time := io.time; cpu.io.externalIrq := io.externalIrq
    cpu.io.timerIrq := io.timerIrq; cpu.io.softwareIrq := io.softwareIrq
    cpu.io.supervisorExternalIrq.foreach(_ := io.supervisorExternalIrq.get); cpu.io.invalidateReservation.foreach(_ := false.B)
    io.retire := cpu.io.retire
    io.cpuTransportIdle := boundary.cpuTransportIdle; io.vpuTransportIdle := boundary.vpuTransportIdle
    val error = Module(new CdcLevel)
    // Register the terminal state decode before crossing; a multi-bit FSM
    // comparator can glitch during legal transitions even when poison is sticky.
    val registeredError = withClockAndReset(vpuClock, vpuRelease.resetOut.asBool) {
        RegNext(vector.io.protocolError, false.B)
    }
    error.clockIn := cpuClock; error.resetIn := cpuRelease.resetOut; error.levelIn := registeredError
    io.protocolError := error.levelOut
}
