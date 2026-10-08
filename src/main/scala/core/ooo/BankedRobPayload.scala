package soc.core.ooo

import chisel3._
import chisel3.util._

/** Allocation-only ROB PC/instruction payload. Two parity banks each have one
  * synchronous write and one asynchronous read: distributed-RAM-friendly, with
  * no added cycle. Validity, recovery, completion and ownership stay in RenameRob.
  * Memory is deliberately not reset; an unallocated entry has no valid consumer.
  */
class BankedRobPayload(entries: Int) extends Module {
    require(entries >= 4 && isPow2(entries))
    private val indexBits = log2Ceil(entries)
    val io = IO(new Bundle {
        val head = Input(UInt(indexBits.W))
        val write = Input(Vec(2, Valid(new Bundle {
            val index = UInt(indexBits.W)
            val data = UInt(96.W)
        })))
        val read = Output(Vec(2, UInt(96.W)))
    })
    val next = (io.head + 1.U)(indexBits - 1, 0)
    val bankData = Wire(Vec(2, UInt(96.W)))
    for (bank <- 0 until 2) {
        val memory = Mem(entries / 2, UInt(96.W))
        val select = io.write.map(w => w.valid && w.bits.index(0) === bank.U)
        assert(PopCount(select) <= 1.U, "ROB allocation writes must occupy distinct parity banks")
        when(select.reduce(_ || _)) {
            val index = Mux(select(0), io.write(0).bits.index, io.write(1).bits.index)
            val data = Mux(select(0), io.write(0).bits.data, io.write(1).bits.data)
            memory.write(index(indexBits - 1, 1), data)
        }
        val readIndex = Mux(io.head(0) === bank.U, io.head, next)
        bankData(bank) := memory.read(readIndex(indexBits - 1, 1))
    }
    io.read(0) := Mux(io.head(0), bankData(1), bankData(0))
    io.read(1) := Mux(io.head(0), bankData(0), bankData(1))
}
