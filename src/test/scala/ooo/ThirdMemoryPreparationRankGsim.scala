package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

/** Exhaustive 16-owner domain; the C++ oracle scans circular age independently. */
class ThirdMemoryPreparationRankGsim extends Module {
    val p = OooParams(robEntries = 16)
    val io = IO(new Bundle {
        val eligible = Input(UInt(16.W)); val head = Input(UInt(4.W))
        val headMask = Input(UInt(16.W))
        val issued = Input(Bool()); val issuedIndex = Input(UInt(4.W))
        val thirdOwner = Output(UInt(16.W)); val thirdIndex = Output(UInt(4.W)); val thirdValid = Output(Bool())
        val decodedOwner = Output(UInt(16.W)); val decodedIndex = Output(UInt(4.W)); val decodedValid = Output(Bool())
        val firstOwner = Output(UInt(16.W)); val firstIndex = Output(UInt(4.W)); val firstValid = Output(Bool())
        val secondOwner = Output(UInt(16.W)); val secondIndex = Output(UInt(4.W)); val secondValid = Output(Bool())
        val useSecond = Output(Bool()); val selectedValid = Output(Bool()); val selectedIndex = Output(UInt(4.W))
    })
    val third = Module(new ThirdMemoryPreparationRank(p))
    third.io.eligible := io.eligible
    third.io.head := io.head
    io.thirdOwner := third.io.owner
    io.thirdIndex := third.io.index
    io.thirdValid := third.io.valid
    val decoded = Module(new ThirdMemoryPreparationRank(p, predecodedHead = true))
    decoded.io.eligible := io.eligible
    decoded.io.head := io.head
    decoded.io.headMask.get := io.headMask
    io.decodedOwner := decoded.io.owner
    io.decodedIndex := decoded.io.index
    io.decodedValid := decoded.io.valid
    val original = Module(new MemoryPreparationSelector(p, parallelRanks = true, predecodedHead = true))
    original.io.eligible := io.eligible
    original.io.head := io.head
    original.io.headMask.get := io.headMask
    original.io.issued := io.issued
    original.io.issuedIndex := io.issuedIndex
    io.firstOwner := original.io.firstOwner
    io.firstIndex := original.io.firstIndex
    io.firstValid := original.io.firstValid
    io.secondOwner := original.io.secondOwner
    io.secondIndex := original.io.secondIndex
    io.secondValid := original.io.secondValid
    io.useSecond := original.io.useSecond
    io.selectedValid := original.io.selectedValid
    io.selectedIndex := original.io.selectedIndex
}
object ThirdMemoryPreparationRankGsimMain extends App {
    require(args.length == 1, "usage: ThirdMemoryPreparationRankGsimMain output-directory")
    ChiselStage.emitCHIRRTLFile(new ThirdMemoryPreparationRankGsim, Array("--target-dir", args.head))
}
