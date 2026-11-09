package spinor_integration

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import vpu.VectorTiming

/** Independent software checks exercise every equality input bit and VSET source form. */
class I1SpinorTimingFixture extends Module {
    val io = IO(new Bundle {
        val left0 = Input(UInt(64.W)); val left1 = Input(UInt(64.W)); val left2 = Input(UInt(64.W))
        val left3 = Input(UInt(64.W)); val left4 = Input(UInt(64.W))
        val right0 = Input(UInt(64.W)); val right1 = Input(UInt(64.W)); val right2 = Input(UInt(64.W))
        val right3 = Input(UInt(64.W)); val right4 = Input(UInt(64.W))
        val instruction = Input(UInt(32.W)); val scalarType = Input(UInt(64.W))
        val sourceAvl = Input(UInt(64.W)); val currentVl = Input(UInt(8.W))
        val equal80 = Output(Bool()); val equal320 = Output(Bool())
        val selectedType = Output(UInt(64.W)); val selectedAvl = Output(UInt(64.W))
    })
    io.equal80 := VectorTiming.equal(Cat(io.left1(15, 0), io.left0), Cat(io.right1(15, 0), io.right0))
    io.equal320 := VectorTiming.equal(Cat(io.left4, io.left3, io.left2, io.left1, io.left0),
        Cat(io.right4, io.right3, io.right2, io.right1, io.right0))
    val (selectedType, selectedAvl) = VectorTiming.vsetOperands(
        io.instruction, io.scalarType, io.sourceAvl, io.currentVl)
    io.selectedType := selectedType
    io.selectedAvl := selectedAvl
}

object I1SpinorTimingMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1SpinorTimingFixture, Array("--target-dir", args.head))
}
