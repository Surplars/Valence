package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage

/** Exercises the CHIRRTL features needed by the new backend, independently of the old SoC. */
class GsimSmoke extends Module {
    val io = IO(new Bundle {
        val enable    = Input(Bool())
        val lhs       = Input(UInt(64.W))
        val rhs       = Input(UInt(64.W))
        val sum       = Output(UInt(64.W))
        val count     = Output(UInt(32.W))
        val write     = Input(Bool())
        val address   = Input(UInt(3.W))
        val writeData = Input(UInt(32.W))
        val mask      = Input(UInt(4.W))
        val read      = Input(Bool())
        val readData  = Output(UInt(32.W))
    })

    val count = RegInit(0.U(32.W))
    when(io.enable) { count := count + 1.U }
    io.count := count
    io.sum   := io.lhs + io.rhs

    val memory = SyncReadMem(8, Vec(4, UInt(8.W)))
    when(io.write) {
        memory.write(io.address, io.writeData.asTypeOf(Vec(4, UInt(8.W))), io.mask.asBools)
    }
    io.readData := memory.read(io.address, io.read).asUInt
}

object GsimSmokeMain extends App {
    ChiselStage.emitCHIRRTLFile(new GsimSmoke, Array("--target-dir", args.headOption.getOrElse("build/gsim/smoke")))
}
