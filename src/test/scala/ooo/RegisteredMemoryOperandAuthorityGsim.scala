package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Actual production helper only. Consumer lifecycle, context, physical start,
  * proof admission and writeback publication remain CPU-integration obligations.
  * All scalar ports avoid the pinned GSIM Vec input setter limitation.
  */
class RegisteredMemoryOperandAuthorityGsim extends Module {
    val io = IO(new Bundle {
        val source1 = Input(UInt(6.W)); val source2 = Input(UInt(6.W))
        val ready1 = Input(Bool()); val ready2 = Input(Bool())
        val stored1 = Input(UInt(64.W)); val stored2 = Input(UInt(64.W))
        val loadValid = Input(Bool()); val loadDestination = Input(UInt(6.W))
        val loadData = Input(UInt(64.W)); val completionValid = Input(Bool())
        val exception = Input(Bool()); val live = Input(Bool())
        val ownerTag = Input(UInt(64.W)); val ownerIndex = Input(UInt(4.W))
        val completionTag = Input(UInt(64.W)); val completionIndex = Input(UInt(4.W))
        val ordinaryLoad = Input(Bool()); val writesRd = Input(Bool())
        val destination = Input(UInt(6.W)); val producerKilled = Input(Bool())
        val useSecond = Input(Bool())
        val hit1 = Output(Bool()); val hit2 = Output(Bool())
        val numericalReady1 = Output(Bool()); val numericalReady2 = Output(Bool())
        val numericalValue1 = Output(UInt(64.W)); val numericalValue2 = Output(UInt(64.W))
        val producerAuthority = Output(Bool()); val forwarded = Output(Bool())
        val captureAllowed = Output(Bool())
    })
    val load = Wire(Valid(UInt(6.W)))
    load.valid := io.loadValid
    load.bits := io.loadDestination
    io.hit1 := RegisteredMemoryOperandAuthority.hit(io.source1, load)
    io.hit2 := RegisteredMemoryOperandAuthority.hit(io.source2, load)
    io.numericalReady1 := RegisteredMemoryOperandAuthority.ready(io.source1, io.ready1, load)
    io.numericalReady2 := RegisteredMemoryOperandAuthority.ready(io.source2, io.ready2, load)
    io.numericalValue1 := RegisteredMemoryOperandAuthority.value(io.source1, io.ready1, io.stored1, load, io.loadData)
    io.numericalValue2 := RegisteredMemoryOperandAuthority.value(io.source2, io.ready2, io.stored2, load, io.loadData)
    io.producerAuthority := RegisteredMemoryOperandAuthority.producerAuthority(load,
        io.completionValid, io.exception, io.live, Cat(io.ownerTag, io.ownerIndex),
        Cat(io.completionTag, io.completionIndex), io.ordinaryLoad, io.writesRd, io.destination)
    io.forwarded := (!io.ready1 && io.hit1) || (io.useSecond && !io.ready2 && io.hit2)
    io.captureAllowed := RegisteredMemoryOperandAuthority.allowed(io.forwarded, io.producerAuthority, io.producerKilled)
}

object RegisteredMemoryOperandAuthorityGsimMain extends App {
    require(args.length == 1)
    ChiselStage.emitCHIRRTLFile(new RegisteredMemoryOperandAuthorityGsim, Array("--target-dir", args.head))
}
