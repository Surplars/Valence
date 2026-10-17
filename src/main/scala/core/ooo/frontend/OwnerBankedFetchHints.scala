package soc.core.ooo

import chisel3._
import chisel3.util._

class FetchHintPayload extends Bundle {
    val pc = UInt(64.W)
    val instruction = UInt(32.W)
    val nextPc = UInt(64.W)
    val aligned = Bool()
    val different = Bool()
}

/** Arbitrary-address training uses one single-writer RAM per lane, never parity banking.
  *
  * The small last-writer table chooses a whole payload, so PC, instruction,
  * successor and qualification bits cannot come from different writes. Higher
  * lane wins same-index collisions. Invalidation wins validity over all writes.
  * Data RAM is unreset and has no bypass: same-cycle reads see the old hint.
  */
class OwnerBankedFetchHints(entries: Int, lanes: Int) extends Module {
    require(Set(8, 16, 32).contains(entries))
    require(lanes >= 1 && lanes <= 4)
    private val indexBits = log2Ceil(entries)
    private val ownerBits = log2Ceil(lanes).max(1)
    val io = IO(new Bundle {
        val write = Input(Vec(lanes, Valid(new Bundle {
            val index = UInt(indexBits.W)
            val data = new FetchHintPayload
        })))
        val address = Input(Vec(lanes, UInt(indexBits.W)))
        val read = Output(Vec(lanes, Valid(new FetchHintPayload)))
        val invalidate = Input(Bool())
    })
    val valid = RegInit(VecInit(Seq.fill(entries)(false.B)))
    val owner = Reg(Vec(entries, UInt(ownerBits.W)))
    val banks = (0 until lanes).map { lane =>
        val memory = Mem(entries, UInt((new FetchHintPayload).getWidth.W)).suggestName(s"writerBank$lane")
        when(io.write(lane).valid) {
            memory.write(io.write(lane).bits.index, io.write(lane).bits.data.asUInt)
        }
        memory
    }
    for (entry <- 0 until entries) {
        for (lane <- 0 until lanes) {
            when(io.write(lane).valid && io.write(lane).bits.index === entry.U) {
                valid(entry) := true.B
                owner(entry) := lane.U
            }
        }
        when(io.invalidate) { valid(entry) := false.B }
    }
    for (port <- 0 until lanes) {
        val index = io.address(port)
        // Gate the uninitialized owner before it can index the bank-result Vec.
        val selected = Mux(valid(index), owner(index), 0.U)
        val data = VecInit(banks.map(_.read(index)))
        io.read(port).valid := valid(index)
        // Invalid payload is intentionally unspecified, as in the register
        // table. Gate only the tiny owner index; do not distribute validity
        // through another 162-bit output mux. Full-tag hit uses read.valid.
        io.read(port).bits := (if (lanes == 1) data(0) else data(selected)).asTypeOf(new FetchHintPayload)
    }
}
