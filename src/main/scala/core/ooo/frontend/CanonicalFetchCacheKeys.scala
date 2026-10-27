package soc.core.ooo

import chisel3._
import chisel3.util._

/** Exact 64-bit keys for the qualified sixteen-set, two-way packet cache.
  *
  * Capacity: 32 rows. One fill per cycle, three all-row query outputs, II=1.
  * Fill is registered; queries are only wiring into the existing window edge.
  * No ready/credit or validity state lives here: the caller retains context,
  * faults, replacement and accepted-response ownership. Invalid row keys are
  * unspecified and must remain gated by the caller's validity/context checks.
  *
  * A = Cat(T[56:0], set[3:0], 000). For offset k=0,1,2,
  * A-8*k uses T unless set<k, then T-1 modulo 2^57. Only sets zero
  * and one need that borrowed high. No address bits are truncated for lookup.
  */
class CanonicalFetchCacheKeys extends Module {
    val io = IO(new Bundle {
        val write = Input(Valid(new Bundle {
            val address = UInt(64.W)
            val way = Bool()
            // High bits of the OLD accepted owner's base minus sixteen.
            val minusTwoHigh = UInt(57.W)
        }))
        val keys = Output(Vec(3, Vec(32, UInt(64.W))))
    })
    val tags = Reg(Vec(16, Vec(2, UInt(57.W))))
    val boundaryHigh = Reg(Vec(2, Vec(2, UInt(57.W))))
    val writeSet = io.write.bits.address(6, 3)
    when(io.write.valid) {
        assert(io.write.bits.address(2, 0) === 0.U,
            "canonical fetch cache fill must be eight-byte aligned")
    }
    for (set <- 0 until 16; way <- 0 until 2) {
        when(io.write.valid && writeSet === set.U && io.write.bits.way === (way == 1).B) {
            tags(set)(way) := io.write.bits.address(63, 7)
            if (set < 2) boundaryHigh(set)(way) := io.write.bits.minusTwoHigh
        }
        for (offset <- 0 to 2) {
            val high = if (set < offset) boundaryHigh(set)(way) else tags(set)(way)
            val index = (set - offset + 16) % 16
            io.keys(offset)(set * 2 + way) := Cat(high, index.U(4.W), 0.U(3.W))
        }
    }
}
