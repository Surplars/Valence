package soc.core.inorder

import chisel3._
import chisel3.util._

/** Synchronous tag lookup, latency 1 and II=1. Each <=64-row bank captures
  * its own read row only on an admitted read for that bank. Compare tags
  * locally before selecting the bank's one-bit result; no wide tag mux.
  * The cache owns valid/invalidate and prevents same-row read/write hazards.
  * Unowned lookup output is unspecified, as with the original synchronous RAM.
  */
class I1CacheTags(sets: Int, tagBits: Int) extends Module {
    require(sets >= 2 && isPow2(sets) && tagBits >= 1)
    private val rows = math.min(64, sets)
    private val banks = sets / rows
    private val rowBits = log2Ceil(rows)
    private val setBits = log2Ceil(sets)
    val io = IO(new Bundle {
        val readValid = Input(Bool())
        val readSet = Input(UInt(setBits.W))
        val expectedTag = Input(UInt(tagBits.W))
        val writeValid = Input(Bool())
        val writeSet = Input(UInt(setBits.W))
        val writeTag = Input(UInt(tagBits.W))
        val matches = Output(Bool())
    })
    def bank(index: UInt): UInt = if (banks == 1) 0.U else index(setBits - 1, rowBits)
    val selectedBank = if (banks == 1) 0.U else RegEnable(bank(io.readSet), io.readValid)
    val hits = (0 until banks).map { index =>
        val memory = Mem(rows, UInt(tagBits.W))
        val readRow = RegEnable(io.readSet(rowBits - 1, 0), io.readValid && bank(io.readSet) === index.U)
        when(io.writeValid && bank(io.writeSet) === index.U) {
            memory.write(io.writeSet(rowBits - 1, 0), io.writeTag)
        }
        selectedBank === index.U && I1TimingMath.equal(memory.read(readRow), io.expectedTag)
    }
    io.matches := hits.reduce(_ || _)
}
