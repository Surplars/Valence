package soc.core.ooo

import chisel3._
import chisel3.util._

/** Two accepted completion writers, without a completion address conflict.
  * nextPc has the two consecutive retirement readers; tval has only the head reader.
  * Each physical memory has one synchronous writer and one asynchronous reader.
  * Ownership, validity and same-cycle bypass remain in RenameRob. Memories and
  * the writer map are deliberately unreset: the caller masks every unwritten row
  * with its existing done bit, preserving the allocation-time zero payload.
  */
class WriterBankedRobCompletionPayload(entries: Int) extends Module {
    require(entries >= 4 && isPow2(entries), "completion payload banks require a power-of-two ROB of at least four rows")
    private val indexBits = log2Ceil(entries)
    val io = IO(new Bundle {
        val head = Input(UInt(indexBits.W))
        val write = Input(Vec(2, Valid(new Bundle {
            val index = UInt(indexBits.W)
            val nextPc = UInt(64.W)
            val tval = UInt(64.W)
        })))
        val nextPc = Output(Vec(2, UInt(64.W)))
        val headTval = Output(UInt(64.W))
    })

    val latestWriter = Reg(Vec(entries, Bool()))
    val next = (io.head + 1.U)(indexBits - 1, 0)
    when(io.write(0).valid && io.write(1).valid) {
        assert(io.write(0).bits.index =/= io.write(1).bits.index,
            "ROB completion authorization must reject duplicate row writers")
    }
    for (writer <- 0 until 2) {
        when(io.write(writer).valid) {
            latestWriter(io.write(writer).bits.index) := (writer == 1).B
        }
    }

    val nextPcRead = Wire(Vec(2, Vec(2, UInt(64.W))))
    val tvalRead = Wire(Vec(2, UInt(64.W)))
    for (writer <- 0 until 2) {
        // A completion can target either parity; distinct writers have distinct
        // memories even when their accepted addresses have the same parity.
        for (parity <- 0 until 2) {
            val memory = Mem(entries / 2, UInt(64.W))
            when(io.write(writer).valid && io.write(writer).bits.index(0) === parity.U) {
                memory.write(io.write(writer).bits.index(indexBits - 1, 1), io.write(writer).bits.nextPc)
            }
            val readIndex = Mux(io.head(0) === parity.U, io.head, next)
            nextPcRead(writer)(parity) := memory.read(readIndex(indexBits - 1, 1))
        }
        val memory = Mem(entries, UInt(64.W))
        when(io.write(writer).valid) {
            memory.write(io.write(writer).bits.index, io.write(writer).bits.tval)
        }
        tvalRead(writer) := memory.read(io.head)
    }
    val headNextPc = VecInit((0 until 2).map(w => Mux(io.head(0), nextPcRead(w)(1), nextPcRead(w)(0))))
    val secondNextPc = VecInit((0 until 2).map(w => Mux(io.head(0), nextPcRead(w)(0), nextPcRead(w)(1))))
    io.nextPc(0) := Mux(latestWriter(io.head), headNextPc(1), headNextPc(0))
    io.nextPc(1) := Mux(latestWriter(next), secondNextPc(1), secondNextPc(0))
    io.headTval := Mux(latestWriter(io.head), tvalRead(1), tvalRead(0))
}
