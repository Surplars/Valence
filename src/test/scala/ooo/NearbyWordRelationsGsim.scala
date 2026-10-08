package soc.core.ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage

/** Raw arithmetic boundary, independent of PMP decoding and permissions. */
class NearbyWordRelationsGsim(wordWidth: Int, maxOffset: Int) extends Module {
    val io = IO(new Bundle {
        val base = Input(UInt(wordWidth.W))
        val bound = Input(UInt(wordWidth.W))
        val boundLeWord = Output(UInt((maxOffset + 1).W))
        val wordLeBound = Output(UInt((maxOffset + 1).W))
    })
    val nearby = new NearbyWordRelations(io.base, maxOffset, balanced = true)
    val compared = nearby.compare(io.bound)
    io.boundLeWord := VecInit(compared.map(_._1)).asUInt
    io.wordLeBound := VecInit(compared.map(_._2)).asUInt
}

object NearbyWordRelationsGsimMain extends App {
    require(args.length == 3)
    ChiselStage.emitCHIRRTLFile(new NearbyWordRelationsGsim(args(1).toInt, args(2).toInt),
        Array("--target-dir", args(0)))
}
