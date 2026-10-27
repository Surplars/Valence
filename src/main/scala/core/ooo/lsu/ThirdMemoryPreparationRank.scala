package soc.core.ooo

import chisel3._
import chisel3.util._

/** Independent combinational third circular rank for advisory load preparation.
  * The original two execution ranks and their late useSecond exclusion are not inputs.
  * Zero registered latency, one mask/result per cycle, no storage or execution credit.
  */
class ThirdMemoryPreparationRank(p: OooParams, predecodedHead: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val eligible = Input(UInt(p.robEntries.W))
        val head = Input(UInt(p.robBits.W))
        val headMask = if (predecodedHead) Some(Input(UInt(p.robEntries.W))) else None
        val owner = Output(UInt(p.robEntries.W))
        val index = Output(UInt(p.robBits.W))
        val valid = Output(Bool())
    })
    val afterHead = io.headMask.getOrElse(VecInit((0 until p.robEntries).map(i => i.U >= io.head)).asUInt)
    // Associative saturating prefix counts (>=1, >=2, >=3). Third does not
    // consume either existing execution rank, and head wrap is explicit.
    def ranks(mask: UInt): (UInt, UInt, UInt, Bool, Bool, Bool) = {
        val summary = (0 until p.robBits).foldLeft(
            (0 until p.robEntries).map(i => (mask(i), false.B, false.B))) { (previous, stage) =>
            val distance = 1 << stage
            previous.indices.map { i =>
                if (i < distance) previous(i)
                else {
                    val (a, aa, aaa) = previous(i - distance)
                    val (b, bb, bbb) = previous(i)
                    (a || b, aa || bb || (a && b), aaa || bbb || (aa && b) || (a && bb))
                }
            }
        }
        val first = VecInit((0 until p.robEntries).map { i =>
            mask(i) && (if (i == 0) true.B else !summary(i - 1)._1)
        }).asUInt
        val second = VecInit((0 until p.robEntries).map { i =>
            mask(i) && (if (i == 0) false.B else summary(i - 1)._1 && !summary(i - 1)._2)
        }).asUInt
        val third = VecInit((0 until p.robEntries).map { i =>
            mask(i) && (if (i == 0) false.B else summary(i - 1)._2 && !summary(i - 1)._3)
        }).asUInt
        (first, second, third, summary.last._1, summary.last._2, summary.last._3)
    }
    val (_, _, afterThird, afterAny, afterTwo, afterThree) = ranks(io.eligible & afterHead)
    val (beforeFirst, beforeSecond, beforeThird, _, _, _) = ranks(io.eligible & ~afterHead)
    io.owner := afterThird |
        (beforeFirst & Fill(p.robEntries, afterTwo && !afterThree)) |
        (beforeSecond & Fill(p.robEntries, afterAny && !afterTwo)) |
        (beforeThird & Fill(p.robEntries, !afterAny))
    io.index := OHToUInt(io.owner)
    io.valid := io.owner.orR
    assert(PopCount(io.owner) <= 1.U && !(io.owner & ~io.eligible).orR,
        "advisory third rank must be a one-hot eligible owner")
}
