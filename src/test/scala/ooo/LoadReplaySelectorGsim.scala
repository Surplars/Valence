package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

class LoadReplaySelectorGsim extends Module {
    private val p = OooParams(robEntries = 16, physicalRegs = 48)
    val io = IO(new Bundle {
        val head = Input(UInt(4.W))
        val checkedValid = Input(Bool())
        val checkedIndex = Input(UInt(4.W))
        val checkedBeat = Input(UInt(61.W))
        val checkedLanes = Input(UInt(8.W))
        val eligible = Input(UInt(16.W))
        val beat0 = Input(UInt(61.W))
        val beat1 = Input(UInt(61.W))
        val lanes0 = Input(UInt(8.W))
        val lanes1 = Input(UInt(8.W))
        val bank = Input(UInt(16.W))
        val valid = Output(Bool())
        val index = Output(UInt(4.W))
        val oneHot = Output(UInt(16.W))
    })
    val selector = Module(new LoadReplaySelector(p))
    selector.io.head := io.head
    selector.io.checkedValid := io.checkedValid
    selector.io.checkedIndex := io.checkedIndex
    selector.io.checkedBeat := io.checkedBeat
    selector.io.checkedLanes := io.checkedLanes
    selector.io.eligible := io.eligible
    for (i <- 0 until 16) {
        selector.io.beats(i) := Mux(io.bank(i), io.beat1, io.beat0)
        selector.io.lanes(i) := Mux(io.bank(i), io.lanes1, io.lanes0)
    }
    io.valid := selector.io.valid
    io.index := selector.io.index
    io.oneHot := selector.io.oneHot
}

object LoadReplaySelectorGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new LoadReplaySelectorGsim, Array("--target-dir", args.head))
}
