package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

class MemoryPreparationSelectorGsim(entries: Int, parallelRanks: Boolean = false) extends Module {
    val p = OooParams(robEntries = entries)
    val io = IO(new Bundle {
        val eligible = Input(UInt(32.W))
        val head = Input(UInt(5.W))
        val issued = Input(Bool())
        val issuedIndex = Input(UInt(5.W))
        val firstValid = Output(Bool())
        val firstIndex = Output(UInt(5.W))
        val secondValid = Output(Bool())
        val secondIndex = Output(UInt(5.W))
        val useSecond = Output(Bool())
        val selectedValid = Output(Bool())
        val selectedIndex = Output(UInt(5.W))
    })
    val planner = Module(new MemoryPreparationSelector(p, parallelRanks))
    planner.io.eligible := io.eligible(p.robEntries - 1, 0)
    planner.io.head := io.head(p.robBits - 1, 0)
    planner.io.issued := io.issued
    planner.io.issuedIndex := io.issuedIndex(p.robBits - 1, 0)
    io.firstValid := planner.io.firstValid
    io.firstIndex := planner.io.firstIndex
    io.secondValid := planner.io.secondValid
    io.secondIndex := planner.io.secondIndex
    io.useSecond := planner.io.useSecond
    io.selectedValid := planner.io.selectedValid
    io.selectedIndex := planner.io.selectedIndex
}
object MemoryPreparationSelectorGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new MemoryPreparationSelectorGsim(args(1).toInt, args.contains("parallel")),
        Array("--target-dir", args.head))
}
