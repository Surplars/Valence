package inorder

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.inorder._

class FiveStageSerialClassFixture extends Module {
    val io = IO(new Bundle {
        val instruction = Input(UInt(32.W))
        val compressed = Input(Bool())
        val serial = Output(UInt(7.W))
    })
    val configs = Seq(
        FiveStageConfig(withC = true),
        FiveStageConfig(withC = true, withA = true),
        FiveStageConfig(withC = true, withA = true, withF = true),
        FiveStageConfig(withC = true, withA = true, withF = true, withD = true),
        FiveStageConfig(withC = true, withF = true, withD = true),
        FiveStageConfig(xlen = 32, withC = true, withA = true),
        FiveStageConfig(withA = true, withF = true, withD = true))
    val hints = configs.map { p =>
        val decoded = Module(new FiveStageDecode(p))
        decoded.io.instruction := io.instruction
        if (p.withC) {
            val expand = Module(new FiveStageCompressed(p.xlen, p.withF, p.withD))
            expand.io.instruction := io.instruction(15, 0)
            when(io.compressed) { decoded.io.instruction := expand.io.expanded }
        }
        val hint = I1SerialPredecode(io.instruction, io.compressed, p)
        assert(hint === decoded.io.control.serial, "raw serial class differs from complete ISA/C expansion")
        hint
    }
    io.serial := VecInit(hints).asUInt
}

object FiveStageSerialClassMain extends App {
    ChiselStage.emitCHIRRTLFile(new FiveStageSerialClassFixture, Array("--target-dir", args.head))
}
