package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

class HomeQualificationGsim(base: BigInt, bytes: BigInt) extends Module {
    val io = IO(new Bundle {
        val address = Input(UInt(64.W))
        val firstTag = Input(UInt(58.W))
        val secondTag = Input(UInt(58.W))
        val firstOwned = Input(Bool())
        val secondOwned = Input(Bool())
        val owned = Output(Bool())
        val inRam = Output(Bool())
    })
    val matches = Module(new ParallelHomeLineMatch)
    matches.io.address := io.address
    matches.io.firstTag := io.firstTag
    matches.io.secondTag := io.secondTag
    matches.io.firstOwned := io.firstOwned
    matches.io.secondOwned := io.secondOwned
    io.owned := matches.io.owned
    io.inRam := HomeRamRange.contains(io.address, 64, base, bytes)
}
object HomeQualificationGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new HomeQualificationGsim(BigInt(args(1), 16), BigInt(args(2))),
        Array("--target-dir", args.head))
}
