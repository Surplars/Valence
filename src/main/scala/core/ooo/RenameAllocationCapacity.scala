package soc.core.ooo

import chisel3._
import chisel3.util._

/** Combinational admission, II=1, no storage or extra cycle.
  * Compute at-least-k free-register thresholds in a balanced tree. Each lane's
  * fresh-register prefix is checked without depending on earlier acceptance or
  * a priority-encoder destination. Actual mappings still use the rename ledger.
  */
class RenameAllocationCapacity(width: Int, physicalRegs: Int) extends Module {
    require(width >= 1 && width <= 6 && physicalRegs > width)
    val io = IO(new Bundle {
        val free = Input(UInt(physicalRegs.W))
        val fresh = Input(UInt(width.W))
        val enough = Output(UInt(width.W))
    })
    def thresholds(bits: Seq[Bool]): Seq[Bool] = {
        if (bits.size == 1) Seq(bits.head)
        else {
            val (a, b) = bits.splitAt(bits.size / 2)
            val left = thresholds(a)
            val right = thresholds(b)
            (1 to width.min(bits.size)).map { count =>
                (0 to count).filter(i => i <= left.size && count - i <= right.size).map { i =>
                    val l = if (i == 0) true.B else left(i - 1)
                    val r = if (count - i == 0) true.B else right(count - i - 1)
                    l && r
                }.reduce(_ || _)
            }
        }
    }
    val available = thresholds((0 until physicalRegs).map(io.free(_)))
    io.enough := VecInit((0 until width).map { lane =>
        val needed = PopCount(io.fresh(lane, 0))
        MuxLookup(needed, false.B)((0.U -> true.B) +:
            (1 to lane + 1).map(i => i.U -> available(i - 1)))
    }).asUInt
}
