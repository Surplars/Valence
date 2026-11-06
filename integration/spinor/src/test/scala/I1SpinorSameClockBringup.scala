package spinor_integration

import chisel3._
import chisel3.util._
import soc.core.inorder._
import soc.integration.spinor.I1SpinorMemoryBridge
import vpu._

/** Same-clock functional fixture only, with real CPU and pinned Spinor.
  * The system architecture uses independent CPU/VPU clocks (VPU 300 MHz).
  * This fixture checks instruction semantics, not production CDC or timing.
  */
class I1SpinorSameClockBringup(val p: FiveStageConfig) extends Module {
    require(p.spinor)
    val io = IO(new Bundle {
        val instructionMemory = new FiveStageBurstPort(p)
        val dataMemory = new FiveStageBurstPort(p)
        val time = Input(UInt(64.W))
        val externalIrq = Input(Bool()); val timerIrq = Input(Bool()); val softwareIrq = Input(Bool())
        val retire = Valid(new FiveStageRetire(p))
        val protocolError = Output(Bool())
    })
    val cpu = Module(new FiveStageCachedCore(p))
    val vector = Module(new SpinorIsolated(config = SpinorParams(hostFcsr = true)))
    val bridge = Module(new I1SpinorMemoryBridge(p))
    io.instructionMemory <> cpu.io.instructionMemory; io.dataMemory <> cpu.io.dataMemory
    cpu.io.time := io.time; cpu.io.externalIrq := io.externalIrq
    cpu.io.timerIrq := io.timerIrq; cpu.io.softwareIrq := io.softwareIrq
    cpu.io.supervisorExternalIrq.foreach(_ := false.B)
    cpu.io.invalidateReservation.foreach(_ := false.B)
    val host = cpu.io.spinor.get
    vector.io.offer.valid := host.command.valid; host.command.ready := vector.io.offer.ready
    vector.io.offer.bits.instruction := host.command.bits.instruction
    vector.io.offer.bits.scalar := host.command.bits.scalar
    vector.io.offer.bits.scalar2 := host.command.bits.scalar2
    vector.io.offer.bits.avl := host.command.bits.avl
    vector.io.offer.bits.token := host.command.bits.token
    vector.io.grant <> host.grant
    def result(out: I1SpinorResult, in: IsolatedResult): Unit = {
        out.token := in.reply.completion.token
        out.instruction := in.reply.completion.instruction
        out.scalar := in.reply.completion.scalar
        out.writesScalar := in.reply.completion.writesScalar
        out.illegal := in.reply.completion.illegal
        out.exception := in.reply.exception; out.cause := in.reply.cause; out.tval := in.reply.tval
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
    bridge.io.tl <> vector.io.tl; cpu.io.spinorMemory.get <> bridge.io.memory
    io.retire := cpu.io.retire
    io.protocolError := vector.io.protocolError
}
