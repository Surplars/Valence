package soc.core.ooo

import chisel3._

/** XLEN comparison: eight parallel byte comparisons and three lexicographic
  * reduction levels. One pair/cycle, combinational, no storage/backpressure.
  * Signed order only changes when the operand sign bits differ.
  */
class BalancedBranchCompare extends Module {
    val io = IO(new Bundle {
        val left = Input(UInt(64.W))
        val right = Input(UInt(64.W))
        val equal = Output(Bool())
        val unsignedLess = Output(Bool())
        val signedLess = Output(Bool())
    })
    var parts: Seq[(Bool, Bool)] = (0 until 8).reverse.map { byte =>
        val a = io.left(8 * byte + 7, 8 * byte)
        val b = io.right(8 * byte + 7, 8 * byte)
        (a < b, a === b)
    }.toSeq
    while (parts.size > 1) {
        parts = parts.grouped(2).map { pair =>
            val (highLess, highEqual) = pair.head
            val (lowLess, lowEqual) = pair(1)
            (highLess || (highEqual && lowLess), highEqual && lowEqual)
        }.toSeq
    }
    io.equal := parts.head._2
    io.unsignedLess := parts.head._1
    io.signedLess := Mux(io.left(63) =/= io.right(63), io.left(63), parts.head._1)
}
