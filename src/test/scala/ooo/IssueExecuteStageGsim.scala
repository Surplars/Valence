package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo.IssueExecuteStage

/** Scalar ports keep the independent queue oracle free of generated Vec ABI. */
class IssueExecuteStageGsim extends Module {
    val io = IO(new Bundle {
        val in0 = Flipped(Decoupled(UInt(64.W)))
        val in1 = Flipped(Decoupled(UInt(64.W)))
        val out0 = Decoupled(UInt(64.W))
        val out1 = Decoupled(UInt(64.W))
        val cancel0 = Input(Bool())
        val cancel1 = Input(Bool())
        val occupied0 = Output(Bool())
        val occupied1 = Output(Bool())
    })
    val first = Module(new IssueExecuteStage(64))
    val second = Module(new IssueExecuteStage(64))
    first.io.enq <> io.in0
    second.io.enq <> io.in1
    io.out0 <> first.io.deq
    io.out1 <> second.io.deq
    first.io.cancel := io.cancel0
    second.io.cancel := io.cancel1
    io.occupied0 := first.io.occupied
    io.occupied1 := second.io.occupied
}

object IssueExecuteStageGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new IssueExecuteStageGsim, Array("--target-dir", args.head))
}
