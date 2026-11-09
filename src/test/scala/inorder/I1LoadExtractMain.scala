package inorder

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.inorder.I1LoadExtract

class I1LoadExtractHarness(xlen: Int) extends Module {
    val io = IO(new Bundle {
        val data = Input(UInt(xlen.W))
        val offset = Input(UInt(log2Ceil(xlen / 8).W))
        val funct3 = Input(UInt(3.W))
        val direct = Input(Bool())
        val fallback = Input(UInt(xlen.W))
        val selected = Input(Bool())
        val shifted = Output(UInt(xlen.W))
        val loaded = Output(UInt(xlen.W))
    })
    val result = I1LoadExtract(io.data, io.offset, io.funct3, io.direct, io.fallback, io.selected)
    io.shifted := result._1
    io.loaded := result._2
}

object I1LoadExtractMain extends App {
    require(args.length == 2)
    ChiselStage.emitCHIRRTLFile(new I1LoadExtractHarness(args(1).toInt), Array("--target-dir", args(0)))
}
