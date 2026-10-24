package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Packed fixture leaves the C++ oracle independent of Vec accessors. */
class DualCompletionSelectorGsim extends Module {
    val p = OooParams(robEntries = 16)
    val io = IO(new Bundle {
        val head = Input(UInt(4.W))
        val present = Input(UInt(6.W))
        val indices = Input(UInt(24.W))
        val seed = Input(UInt(64.W))
        val first = Output(UInt(6.W))
        val second = Output(UInt(6.W))
        val selected = Output(UInt(6.W))
        val data0 = Output(UInt(64.W))
        val data1 = Output(UInt(64.W))
    })
    val selector = Module(new DualCompletionSelector(p))
    selector.io.head := io.head
    selector.io.present := io.present
    for (i <- 0 until 6) selector.io.index(i) := io.indices(4 * i + 3, 4 * i)
    io.first := selector.io.owners(0)
    io.second := selector.io.owners(1)
    io.selected := selector.io.selected
    val data = (0 until 6).map(i => io.seed ^ (BigInt(i + 1) * BigInt("102030405060708", 16)).U(64.W))
    io.data0 := CircularIssueSelector.selectPayload(selector.io.owners(0), data)
    io.data1 := CircularIssueSelector.selectPayload(selector.io.owners(1), data)
}

object DualCompletionSelectorGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new DualCompletionSelectorGsim, Array("--target-dir", args.head))
}
