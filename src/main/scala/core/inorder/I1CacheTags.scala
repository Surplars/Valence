package soc.core.inorder

import chisel3._
import chisel3.util._

/** Synchronous tag lookup, latency 1 and II=1. Each <=64-row bank compares
  * the offered row/tag before the existing read edge, then captures one hit bit.
  * The following cache response only reduces the registered, bank-qualified hits.
  * Valid bits share the same bank and read edge; cache control supplies install,
  * erase and whole-cache invalidation, and prevents owned read/write hazards.
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
        val eraseValid = Input(Bool())
        val eraseSet = Input(UInt(setBits.W))
        val invalidate = Input(Bool())
        val matches = Output(Bool())
    })
    def bank(index: UInt): UInt = if (banks == 1) 0.U else index(setBits - 1, rowBits)
    val hits = (0 until banks).map { index =>
        val memory = Mem(rows, UInt(tagBits.W))
        val valid = RegInit(0.U(rows.W))
        val selected = bank(io.readSet) === index.U
        // Capture bank selection at the same read edge as tag/presence. The
        // response then needs an OR reduction, with no late bank-select mux.
        val matched = RegEnable(selected && valid(io.readSet(rowBits - 1, 0)) && !io.invalidate &&
            I1TimingMath.equal(memory.read(io.readSet(rowBits - 1, 0)), io.expectedTag), io.readValid)
        when(io.writeValid && bank(io.writeSet) === index.U) {
            memory.write(io.writeSet(rowBits - 1, 0), io.writeTag)
            valid := valid | UIntToOH(io.writeSet(rowBits - 1, 0), rows)
        }
        when(io.eraseValid && bank(io.eraseSet) === index.U) {
            valid := valid & ~UIntToOH(io.eraseSet(rowBits - 1, 0), rows)
        }
        when(io.invalidate) { valid := 0.U }
        matched
    }
    io.matches := hits.reduce(_ || _)
}
