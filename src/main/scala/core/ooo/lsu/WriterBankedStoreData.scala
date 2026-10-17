package soc.core.ooo

import chisel3._
import chisel3.util._

/** Experimental payload-only store data for the default-OFF backend candidate.
  * Two arbitrary write addresses, N independent asynchronous reads, no added latency.
  * This uses the last-writer pattern of WriterBankedRobCompletionPayload, without
  * its retirement-reader/parity assumptions. Row zero is ordinary writable data.
  * Higher write lane wins a same-row collision, matching Reg(Vec) last-connect.
  * Reads have no write-through: before the edge they see old data; after the edge
  * they see the winning write. Disabled reads are zero (the zero-onehot contract).
  * RAM and writer metadata are intentionally unreset. An unwritten row is
  * unspecified; the caller must retain prepared/live/full-owner authorization,
  * clear it on reset/reuse/kill, and write before making a row observable again.
  * Reset does not inhibit writes, exactly as for the original unreset payload Reg.
  */
class WriterBankedStoreData(entries: Int, readPorts: Int) extends Module {
    require(entries >= 2 && isPow2(entries))
    require(readPorts >= 1)
    private val indexBits = log2Ceil(entries)
    val io = IO(new Bundle {
        val write = Input(Vec(2, Valid(new Bundle {
            val index = UInt(indexBits.W)
            val data = UInt(64.W)
        })))
        val address = Input(Vec(readPorts, UInt(indexBits.W)))
        val enable = Input(Vec(readPorts, Bool()))
        val data = Output(Vec(readPorts, UInt(64.W)))
    })
    val latestWriter = Reg(Vec(entries, Bool()))
    val banks = Seq.fill(2)(Mem(entries, UInt(64.W)))
    for (lane <- 0 until 2) {
        when(io.write(lane).valid) {
            banks(lane).write(io.write(lane).bits.index, io.write(lane).bits.data)
            latestWriter(io.write(lane).bits.index) := (lane == 1).B
        }
    }
    for (port <- 0 until readPorts) {
        val data0 = banks(0).read(io.address(port))
        val data1 = banks(1).read(io.address(port))
        io.data(port) := Mux(io.enable(port), Mux(latestWriter(io.address(port)), data1, data0), 0.U)
    }
}
