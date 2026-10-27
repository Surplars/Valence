package soc.core.ooo

import chisel3._
import chisel3.util._

/** Payload storage for two already accepted ROB completions per cycle.
  *
  * Capacity is entries rows. Writes may address any two distinct rows, including
  * equal parity. Data and nextPc have two consecutive asynchronous readers;
  * tval has the head reader only. Read latency is zero and sustained II is one.
  * There is no write-through, credit, backpressure or owner authorization here.
  * The caller retains full-token admission, done masking and same-cycle bypass.
  *
  * Each writer owns two parity banks of Cat(data, nextPc) and one tval bank.
  * All fields share the same unreset last-writer directory. Allocation, recovery,
  * retirement and reset do not clear this payload or suppress its writes. The
  * caller must reconstruct allocation-zero semantics using its unchanged done
  * state, including raw output bits whose enclosing valid is false.
  */
class DualWriterRobCompletionData(entries: Int) extends Module {
    require(entries >= 4 && isPow2(entries), "ROB completion data requires a power-of-two row count of at least four")
    private val indexBits = log2Ceil(entries)
    val io = IO(new Bundle {
        val head = Input(UInt(indexBits.W))
        val write = Input(Vec(2, Valid(new Bundle {
            val index = UInt(indexBits.W)
            val data = UInt(64.W)
            val nextPc = UInt(64.W)
            val tval = UInt(64.W)
        })))
        val data = Output(Vec(2, UInt(64.W)))
        val nextPc = Output(Vec(2, UInt(64.W)))
        val headTval = Output(UInt(64.W))
    })

    val latestWriter = Reg(Vec(entries, Bool()))
    val next = (io.head + 1.U)(indexBits - 1, 0)
    when(io.write(0).valid && io.write(1).valid) {
        assert(io.write(0).bits.index =/= io.write(1).bits.index,
            "ROB completion payload accepts only distinct writer rows")
    }

    val packedRead = Wire(Vec(2, Vec(2, UInt(128.W))))
    val tvalRead = Wire(Vec(2, UInt(64.W)))
    for (writer <- 0 until 2) {
        val write = io.write(writer)
        when(write.valid) {
            latestWriter(write.bits.index) := (writer == 1).B
        }
        for (parity <- 0 until 2) {
            val memory = Mem(entries / 2, UInt(128.W)).suggestName(s"completionWriter${writer}Parity$parity")
            when(write.valid && write.bits.index(0) === parity.U) {
                memory.write(write.bits.index(indexBits - 1, 1), Cat(write.bits.data, write.bits.nextPc))
            }
            // Consecutive readers have opposite parity, including the wrap pair.
            val readIndex = Mux(io.head(0) === parity.U, io.head, next)
            packedRead(writer)(parity) := memory.read(readIndex(indexBits - 1, 1))
        }
        val memory = Mem(entries, UInt(64.W)).suggestName(s"tvalWriter$writer")
        when(write.valid) {
            memory.write(write.bits.index, write.bits.tval)
        }
        tvalRead(writer) := memory.read(io.head)
    }

    val headPacked = VecInit((0 until 2).map(writer =>
        Mux(io.head(0), packedRead(writer)(1), packedRead(writer)(0))))
    val nextPacked = VecInit((0 until 2).map(writer =>
        Mux(io.head(0), packedRead(writer)(0), packedRead(writer)(1))))
    val selectedHead = Mux(latestWriter(io.head), headPacked(1), headPacked(0))
    val selectedNext = Mux(latestWriter(next), nextPacked(1), nextPacked(0))
    io.data(0) := selectedHead(127, 64)
    io.data(1) := selectedNext(127, 64)
    io.nextPc(0) := selectedHead(63, 0)
    io.nextPc(1) := selectedNext(63, 0)
    io.headTval := Mux(latestWriter(io.head), tvalRead(1), tvalRead(0))
}
