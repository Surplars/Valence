package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

class ReturnStackGsim(parallelControl: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val commit0 = Input(Valid(new ReturnStackCommit))
        val commit1 = Input(Valid(new ReturnStackCommit))
        val available = Output(Bool())
        val target = Output(UInt(64.W))
        val occupancy = Output(UInt(4.W))
    })
    val stack = Module(new RetirementReturnStack(8, 2, pcDerivedLinks = true, parallelControl = parallelControl))
    stack.io.commit(0) := io.commit0
    stack.io.commit(1) := io.commit1
    io.available := stack.io.available
    io.target := stack.io.target
    io.occupancy := stack.io.occupancy
}

object ReturnStackGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new ReturnStackGsim(args.drop(1).contains("parallel-control")),
        Array("--target-dir", args.head))
}
