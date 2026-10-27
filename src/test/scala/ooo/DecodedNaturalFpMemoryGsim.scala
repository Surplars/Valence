package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

class DecodedNaturalFpMemoryGsim extends Module {
    val p = soc.platform.CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2.config.coreParams
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

object DecodedNaturalFpMemoryGsimMain extends App {
    require(args.length == 1, "output-directory")
    ChiselStage.emitCHIRRTLFile(new DecodedNaturalFpMemoryGsim, Array("--target-dir", args.head))
}
