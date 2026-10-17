package soc.core.ooo

import chisel3._
import chisel3.util._

/** Configurable ROB-head-only F/D bridge. One outstanding command;
  * completion is offered once, while architectural FP state waits for real ROB
  * retirement. Faulted commands are discarded on the eventual precise trap.
  * CSR/FS requests are already irrevocably authorized by MachineSystemUnit.
  */
class FloatingPointSystem(p: OooParams) extends Module {
    val io = IO(new Bundle {
        val start = Flipped(Decoupled(new SystemRequest(p)))
        val complete = Decoupled(new BackendCompletion(p))
        val retire = Input(Valid(new RobToken(p)))
        val trap = Input(Bool())
        val csr = Flipped(Decoupled(new FloatingPointCsr))
        val setFs = Flipped(Decoupled(UInt(2.W)))
        val fs = Output(UInt(2.W))
        val fcsr = Output(UInt(8.W))
        val busy = Output(Bool())
        val memory = new DataPort
        val memoryBusy = Output(Bool())
        val pmpState = Input(new PmpState)
        val dataPrivilege = Input(UInt(2.W))
        val virtualized = Input(Bool())
    })
    val fp = Module(new FloatingPointState(p))
    val execute = Module(new FloatingPointExecute(p, p.fpConfig))
    // Memory has its own explicit request/response/drain contract. Architectural
    // FP state and arithmetic completion selection do not implement an LSU.
    val memoryOption = if (p.fpConfig.memory) Some(Module(new FloatingPointMemoryPipeline(p))) else None
    io.memory.request.valid := false.B
    io.memory.request.bits := 0.U.asTypeOf(new DataRequest)
    io.memory.response.ready := false.B
    io.memoryBusy := false.B
    memoryOption.foreach { memory =>
        io.memory <> memory.io.memory
        io.memoryBusy := memory.io.busy
        memory.io.trap := io.trap
        memory.io.pmpState := io.pmpState
        memory.io.dataPrivilege := io.dataPrivilege
        memory.io.virtualized := io.virtualized
    }
    val pc = Reg(UInt(64.W))
    memoryOption.foreach(_.io.pc := pc)
    val sent = RegInit(false.B)
    fp.io.headAuthorized := true.B
    fp.io.flush := io.trap
    fp.io.retire := io.retire
    fp.io.csr <> io.csr
    fp.io.setFs <> io.setFs
    io.fs := fp.io.fs
    io.fcsr := fp.io.fcsr
    io.busy := fp.io.busy
    val inst = io.start.bits.instruction
    fp.io.issue.valid := io.start.valid
    io.start.ready := fp.io.issue.ready
    fp.io.issue.bits := 0.U.asTypeOf(new FloatingPointCommand(p))
    fp.io.issue.bits.token := io.start.bits.token
    fp.io.issue.bits.instruction := inst
    fp.io.issue.bits.sources(0) := inst(19, 15)
    fp.io.issue.bits.sources(1) := inst(24, 20)
    fp.io.issue.bits.sources(2) := inst(31, 27)
    for (lane <- 0 until 3) {
        fp.io.issue.bits.checkSingleBox(lane) := FloatingPointDecode.checkSingle(inst)
    }
    fp.io.issue.bits.integerSource := io.start.bits.operand
    fp.io.issue.bits.destination := inst(11, 7)
    fp.io.issue.bits.singleResult := FloatingPointDecode.single(inst)
    fp.io.issue.bits.writesFp := FloatingPointDecode.writesFp(inst)
    fp.io.issue.bits.writesFlags := FloatingPointDecode.writesFlags(inst)
    fp.io.issue.bits.usesRounding := FloatingPointDecode.usesRounding(inst)
    fp.io.issue.bits.rounding := inst(14, 12)
    when(io.start.fire) {
        assert(FloatingPointDecode.supported(inst, p.fpConfig), "unsupported instruction entered FP system bridge")
        pc := io.start.bits.pc
        sent := false.B
    }

    val executeInst = fp.io.execute.bits.command.instruction
    val executeMemory = FloatingPointSubset.memory(executeInst)
    execute.io.flush := io.trap
    execute.io.request.valid := fp.io.execute.valid && !executeMemory
    execute.io.request.bits := fp.io.execute.bits
    fp.io.execute.ready := execute.io.request.ready && !executeMemory
    val memoryComplete = Wire(Decoupled(new BackendCompletion(p)))
    memoryComplete.valid := false.B
    memoryComplete.bits := 0.U.asTypeOf(new BackendCompletion(p))
    memoryOption.foreach { memory =>
        memory.io.execute.valid := fp.io.execute.valid && executeMemory
        memory.io.execute.bits := fp.io.execute.bits
        memoryComplete <> memory.io.complete
        when(executeMemory) { fp.io.execute.ready := memory.io.execute.ready }
    }
    val memoryResult = WireDefault(0.U.asTypeOf(new FloatingPointResult(p)))
    memoryResult.token := memoryComplete.bits.token
    memoryResult.value := memoryComplete.bits.data
    memoryResult.exception := memoryComplete.bits.exception
    memoryResult.cause := memoryComplete.bits.cause
    memoryResult.tval := memoryComplete.bits.tval
    fp.io.result.valid := execute.io.result.valid || memoryComplete.valid
    fp.io.result.bits := Mux(memoryComplete.valid, memoryResult, execute.io.result.bits)
    execute.io.result.ready := fp.io.result.ready && !memoryComplete.valid
    memoryComplete.ready := fp.io.result.ready && !execute.io.result.valid
    assert(PopCount(Seq(execute.io.result.valid, memoryComplete.valid)) <= 1.U,
        "one outstanding FP producer")
    when(io.trap) { sent := false.B }

    io.complete.valid := fp.io.complete.valid && !sent
    io.complete.bits := 0.U.asTypeOf(new BackendCompletion(p))
    io.complete.bits.token := fp.io.complete.bits.token
    io.complete.bits.data := fp.io.complete.bits.value
    io.complete.bits.nextPc := pc + 4.U
    io.complete.bits.exception := fp.io.complete.bits.exception
    io.complete.bits.cause := fp.io.complete.bits.cause
    io.complete.bits.tval := fp.io.complete.bits.tval
    when(io.complete.fire) { sent := true.B }
}
