package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

class FpMemoryPipelineGsim extends Module {
    val p = OooParams(machineSystem = true, pmpEntries = 16, floatingPoint = FloatingPointConfig.fullFD)
    val io = IO(new Bundle {
        val valid = Input(Bool())
        val ready = Output(Bool())
        val instruction = Input(UInt(32.W))
        val base = Input(UInt(64.W))
        val data = Input(UInt(64.W))
        val pc = Input(UInt(64.W))
        val tag = Input(UInt(32.W))
        val cfg = Input(UInt(8.W))
        val pmpAddress = Input(UInt(54.W))
        val privilege = Input(UInt(2.W))
        val virtualized = Input(Bool())
        val trap = Input(Bool())
        val memory = new DataPort
        val completeReady = Input(Bool())
        val completeValid = Output(Bool())
        val value = Output(UInt(64.W))
        val exception = Output(Bool())
        val cause = Output(UInt(6.W))
        val tval = Output(UInt(64.W))
        val nextPc = Output(UInt(64.W))
        val resultTag = Output(UInt(32.W))
        val busy = Output(Bool())
    })
    val memory = Module(new FloatingPointMemoryPipeline(p))
    val state = WireDefault(0.U.asTypeOf(new PmpState))
    state.cfg(0) := io.cfg
    state.addr(0) := io.pmpAddress
    PmpState.decodeRegions(state)
    memory.io.pmpState := state
    memory.io.dataPrivilege := io.privilege
    memory.io.virtualized := io.virtualized
    memory.io.pc := io.pc
    memory.io.trap := io.trap
    memory.io.execute.valid := io.valid
    memory.io.execute.bits := 0.U.asTypeOf(new FloatingPointExecution(p))
    memory.io.execute.bits.command.token := io.tag.asTypeOf(new RobToken(p))
    memory.io.execute.bits.command.instruction := io.instruction
    memory.io.execute.bits.command.integerSource := io.base
    memory.io.execute.bits.operands(1) := io.data
    io.ready := memory.io.execute.ready
    io.memory <> memory.io.memory
    memory.io.complete.ready := io.completeReady
    io.completeValid := memory.io.complete.valid
    io.value := memory.io.complete.bits.data
    io.exception := memory.io.complete.bits.exception
    io.cause := memory.io.complete.bits.cause
    io.tval := memory.io.complete.bits.tval
    io.nextPc := memory.io.complete.bits.nextPc
    io.resultTag := memory.io.complete.bits.token.asUInt(31, 0)
    io.busy := memory.io.busy
}

class TranslationContextGsim extends Module {
    val p = BoardSocConfig.timingParams("staged-fetch-feedback").copy(
        machineSystem = true, pmpEntries = 16, virtualMemoryLevels = 3)
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val physical = new DataPort
        val translation = new SvTranslationPort
        val context = Input(new VmCsrState)
        val idle = Output(Bool())
    })
    val adapter = Module(new DataTranslationAdapter(p, registerCheckedRequests = true))
    adapter.io.virtual <> io.upstream
    io.physical <> adapter.io.physical
    io.translation <> adapter.io.translation
    adapter.io.vmState := io.context
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := "h1f".U
    pmp.addr(0) := ((BigInt(1) << 54) - 1).U
    PmpState.decodeRegions(pmp)
    adapter.io.pmpState := pmp
    io.idle := adapter.io.idle
}

class CursorNeighborGsim extends Module {
    val io = IO(new Bundle {
        val value = Input(UInt(64.W))
        val plus43 = Output(UInt(43.W))
        val minus43 = Output(UInt(43.W))
        val plus64 = Output(UInt(64.W))
        val minus64 = Output(UInt(64.W))
    })
    io.plus43 := TimingArithmetic.neighbor(io.value(42, 0))
    io.minus43 := TimingArithmetic.neighbor(io.value(42, 0), decrement = true)
    io.plus64 := TimingArithmetic.neighbor(io.value)
    io.minus64 := TimingArithmetic.neighbor(io.value, decrement = true)
}

object FpMemoryPipelineGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FpMemoryPipelineGsim, Array("--target-dir", args.head))
}
object TranslationContextGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TranslationContextGsim, Array("--target-dir", args.head))
}
object CursorNeighborGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new CursorNeighborGsim, Array("--target-dir", args.head))
}
