package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo.CompactFetchCacheKeys

/** Read mux is test plumbing only; the production helper exports all three keys in parallel. */
class CompactFetchCacheKeysGsim(sets: Int = 16) extends Module {
    val io = IO(new Bundle {
        val writeEnable = Input(Bool())
        val writeAddress = Input(UInt(64.W))
        val writeWay = Input(Bool())
        val writeMinusHigh = Input(UInt((61 - log2Ceil(sets)).W))
        val readSlot = Input(UInt(log2Ceil(sets * 2).W))
        val key0 = Output(UInt(64.W))
        val key1 = Output(UInt(64.W))
        val key2 = Output(UInt(64.W))
    })
    val keys = Module(new CompactFetchCacheKeys(sets))
    keys.io.write.valid := io.writeEnable
    keys.io.write.bits.address := io.writeAddress
    keys.io.write.bits.way := io.writeWay
    keys.io.write.bits.minusTwoHigh := io.writeMinusHigh
    io.key0 := keys.io.keys(0)(io.readSlot)
    io.key1 := keys.io.keys(1)(io.readSlot)
    io.key2 := keys.io.keys(2)(io.readSlot)
}

object CompactFetchCacheKeysGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new CompactFetchCacheKeysGsim(args.lift(1).map(_.toInt).getOrElse(16)),
        Array("--target-dir", args.head))
}
