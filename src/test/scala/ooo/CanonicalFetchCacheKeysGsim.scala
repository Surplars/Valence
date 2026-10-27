package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo.CanonicalFetchCacheKeys

/** Read mux is test plumbing only; the production helper exports all three keys in parallel. */
class CanonicalFetchCacheKeysGsim(mutation: String = "none") extends Module {
    require(Set("none", "wrong-borrow", "truncate-high").contains(mutation))
    val io = IO(new Bundle {
        val writeEnable = Input(Bool())
        val writeAddress = Input(UInt(64.W))
        val writeWay = Input(Bool())
        val writeMinusHigh = Input(UInt(57.W))
        val readSlot = Input(UInt(5.W))
        val key0 = Output(UInt(64.W))
        val key1 = Output(UInt(64.W))
        val key2 = Output(UInt(64.W))
    })
    val keys = Module(new CanonicalFetchCacheKeys)
    keys.io.write.valid := io.writeEnable
    // Test-only boundary fault injection; production helper is not modified.
    keys.io.write.bits.address := (if (mutation == "truncate-high")
        Cat(0.U(32.W), io.writeAddress(31, 0)) else io.writeAddress)
    keys.io.write.bits.way := io.writeWay
    keys.io.write.bits.minusTwoHigh := (if (mutation == "wrong-borrow")
        io.writeAddress(63, 7) else io.writeMinusHigh)
    io.key0 := keys.io.keys(0)(io.readSlot)
    io.key1 := keys.io.keys(1)(io.readSlot)
    io.key2 := keys.io.keys(2)(io.readSlot)
}

object CanonicalFetchCacheKeysGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new CanonicalFetchCacheKeysGsim(args.lift(1).getOrElse("none")),
        Array("--target-dir", args.head))
}
