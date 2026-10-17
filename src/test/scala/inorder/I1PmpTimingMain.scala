package inorder

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.inorder._

/** Scalar configuration writer avoids simulator top-level Vec accessor limits. */
class I1PmpTimingFixture(width: Int, staged: Boolean = false) extends Module {
    val p = FiveStageConfig(xlen = width, pmpEntries = 8, pipelineProfile = "fpga8", fpgaTimingCuts = true)
    val io = IO(new Bundle {
        val writeEntry = Input(Bool()); val index = Input(UInt(3.W))
        val lower = Input(UInt((p.physicalBits + 1).W)); val upper = Input(UInt((p.physicalBits + 1).W))
        val config = Input(UInt(8.W)); val address = Input(UInt(width.W)); val size = Input(UInt(4.W))
        val privilege = Input(UInt(2.W)); val execute = Input(Bool()); val store = Input(Bool())
        val allow = Output(Bool())
        val capture = if (staged) Some(Input(Bool())) else None
    })
    val entries = RegInit(0.U.asTypeOf(Vec(8, new FiveStagePmpEntry(p))))
    when(io.writeEntry) {
        entries(io.index).lower := io.lower; entries(io.index).upper := io.upper
        entries(io.index).config := io.config
    }
    val dut = Module(new FiveStagePmp(p, registerComparisons = staged))
    dut.io.capture.foreach(_ := io.capture.get)
    dut.io.entries := entries; dut.io.address := io.address; dut.io.size := io.size
    dut.io.privilege := io.privilege; dut.io.execute := io.execute; dut.io.write := io.store
    io.allow := dut.io.allow
}
object I1PmpTimingMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1PmpTimingFixture(args(1).toInt, args.contains("--staged")),
        Array("--target-dir", args.head))
}
