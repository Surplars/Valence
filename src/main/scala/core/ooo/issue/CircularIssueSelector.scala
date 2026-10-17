package soc.core.ooo

import chisel3._
import chisel3.util._

object CircularIssueSelector {
    /** Explicit masked OR, including a defined zero payload for the empty mask.
      * Do not rely on the unspecified no-hot case of a generic one-hot mux.
      */
    def selectPayload(oneHot: UInt, payloads: Seq[UInt]): UInt = {
        require(payloads.nonEmpty && oneHot.getWidth == payloads.size)
        val width = payloads.head.getWidth
        require(payloads.forall(_.getWidth == width))
        payloads.zipWithIndex.map { case (data, i) => data & Fill(width, oneHot(i)) }.reduce(_ | _)
    }
}

/** Combinational oldest-two circular ROB selection. One-hot payload selection avoids
  * serial age tournaments followed by index re-decode; grant/kill stays downstream.
  * No state, new issue lane, queue capacity or additional execution cycle.
  */
class CircularIssueSelector(p: OooParams, parallelRanks: Boolean = false,
    predecodedHead: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val eligible = Input(UInt(p.robEntries.W))
        val head = Input(UInt(p.robBits.W))
        val headMask = if (predecodedHead) Some(Input(UInt(p.robEntries.W))) else None
        val first = Output(UInt(p.robEntries.W))
        val second = Output(UInt(p.robEntries.W))
        val firstValid = Output(Bool())
        val secondValid = Output(Bool())
        val firstIndex = Output(UInt(p.robBits.W))
        val secondIndex = Output(UInt(p.robBits.W))
    })
    val afterHead = io.headMask.getOrElse(VecInit((0 until p.robEntries).map(i => i.U >= io.head)).asUInt)
    def oldest(mask: UInt): UInt = {
        val laterSlots = mask & afterHead
        PriorityEncoderOH(Mux(laterSlots.orR, laterSlots, mask))
    }
    if (parallelRanks) {
        // Associative saturating prefix summaries: (any, atLeastTwo). Neither
        // rank consumes the other rank's payload/mask. Head-wrap is explicit.
        def ranks(mask: UInt): (UInt, UInt, Bool, Bool) = {
            val summary = (0 until p.robBits).foldLeft(
                (0 until p.robEntries).map(i => (mask(i), false.B))) { (previous, stage) =>
                val distance = 1 << stage
                previous.indices.map { i =>
                    if (i < distance) previous(i)
                    else {
                        val (a, aa) = previous(i - distance)
                        val (b, bb) = previous(i)
                        (a || b, aa || bb || (a && b))
                    }
                }
            }
            val first = VecInit((0 until p.robEntries).map { i =>
                mask(i) && (if (i == 0) true.B else !summary(i - 1)._1)
            }).asUInt
            val second = VecInit((0 until p.robEntries).map { i =>
                mask(i) && (if (i == 0) false.B else summary(i - 1)._1 && !summary(i - 1)._2)
            }).asUInt
            (first, second, summary.last._1, summary.last._2)
        }
        val (afterFirst, afterSecond, afterAny, afterTwo) = ranks(io.eligible & afterHead)
        val (beforeFirst, beforeSecond, beforeAny, beforeTwo) = ranks(io.eligible & ~afterHead)
        io.first := afterFirst | (beforeFirst & Fill(p.robEntries, !afterAny))
        io.second := afterSecond |
            (beforeFirst & Fill(p.robEntries, afterAny && !afterTwo)) |
            (beforeSecond & Fill(p.robEntries, !afterAny))
        io.firstValid := afterAny || beforeAny
        io.secondValid := afterTwo || (afterAny && beforeAny) || beforeTwo
    } else {
        io.first := oldest(io.eligible)
        val remaining = io.eligible & ~io.first
        io.second := oldest(remaining)
        io.firstValid := io.eligible.orR
        io.secondValid := remaining.orR
    }
    io.firstIndex := OHToUInt(io.first)
    io.secondIndex := OHToUInt(io.second)
    assert(PopCount(io.first) <= 1.U && PopCount(io.second) <= 1.U && !(io.first & io.second).orR,
        "issue payload owners must be distinct one-hot choices")
}
