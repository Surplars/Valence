package soc.core.ooo

import chisel3._
import chisel3.util._

/** Full-address keys for three parallel two-wide fetch packet queries.
  * A row at set s holds an aligned address (T * sets + s) * 8. Subtracting
  * one/two packets borrows from T only at sets zero/one. Preserve one original
  * full base per row and only those four borrowed high tags, not two complete
  * shifted copies of every row. Query reconstruction is wiring/constant bits;
  * no query-side wide arithmetic, added cycle, or shortened address comparison.
  * Valid/context/payload ownership stays with SynchronousFetch.
  */
class CompactFetchCacheKeys(sets: Int) extends Module {
    require(sets >= 4 && sets <= 256 && isPow2(sets),
        "compact fetch keys require four through256 power-of-two sets")
    private val setBits = log2Ceil(sets)
    private val highLow = setBits + 3
    private val highBits = 64 - highLow
    val io = IO(new Bundle {
        val write = Input(Valid(new Bundle {
            val address = UInt(64.W)
            val way = Bool()
            // Already computed from the accepted request, never the query PC.
            val minusTwoHigh = UInt(highBits.W)
        }))
        val keys = Output(Vec(3, Vec(sets * 2, UInt(64.W))))
    })
    val bases = Reg(Vec(sets, Vec(2, UInt(64.W))))
    val boundaryHigh = Reg(Vec(2, Vec(2, UInt(highBits.W))))
    val writeSet = io.write.bits.address(highLow - 1, 3)
    when(io.write.valid) {
        assert(io.write.bits.address(2, 0) === 0.U, "compact fetch cache fill must be eight-byte aligned")
    }
    for (set <- 0 until sets; way <- 0 until 2) {
        when(io.write.valid && writeSet === set.U && io.write.bits.way === (way == 1).B) {
            bases(set)(way) := io.write.bits.address
            if (set < 2) boundaryHigh(set)(way) := io.write.bits.minusTwoHigh
        }
        io.keys(0)(set * 2 + way) := bases(set)(way)
        for (offset <- 1 to 2) {
            val high = if (set < offset) boundaryHigh(set)(way) else bases(set)(way)(63, highLow)
            val index = (set - offset + sets) % sets
            io.keys(offset)(set * 2 + way) := Cat(high, index.U(setBits.W), 0.U(3.W))
        }
    }
}
