package soc.core.ooo

import chisel3._
import chisel3.util._

/** Oldest eligible ordinary load not already offered or recently reserved.
  *
  * Combinational: zero registered latency, one selection per cycle, no storage,
  * backpressure or execution/permission credit. Reuses the existing advisory PRF
  * read and AGU; it never changes either execution rank. The caller supplies all
  * ordinary-load/live/virtualized/registered-source-ready eligibility restrictions.
  * firstOwner/secondOwner are the original raw early execution planner owners,
  * NOT the first two owners recomputed from the filtered ordinary-load set.
  * exclusionMask is a registered index-only hint; ABA can only overexclude here.
  * A zero mask agrees with old rank three only for all-ordinary eligible traffic.
  */
class OldestUncoveredMemoryPreparation(p: OooParams, predecodedHead: Boolean = false) extends Module {
    require(p.robEntries == 16, "oldest uncovered advisory supply is qualified only for ROB16")
    val io = IO(new Bundle {
        val eligible = Input(UInt(p.robEntries.W))
        val head = Input(UInt(p.robBits.W))
        val headMask = if (predecodedHead) Some(Input(UInt(p.robEntries.W))) else None
        val firstOwner = Input(UInt(p.robEntries.W))
        val secondOwner = Input(UInt(p.robEntries.W))
        val exclusionMask = Input(UInt(p.robEntries.W))
        val owner = Output(UInt(p.robEntries.W))
        val index = Output(UInt(p.robBits.W))
        val valid = Output(Bool())
    })

    val uncovered = io.eligible & ~(io.firstOwner | io.secondOwner | io.exclusionMask)
    val afterHeadMask = io.headMask.getOrElse(VecInit((0 until p.robEntries).map(i => i.U >= io.head)).asUInt)
    val afterHead = uncovered & afterHeadMask
    io.owner := PriorityEncoderOH(Mux(afterHead.orR, afterHead, uncovered))
    io.index := OHToUInt(io.owner)
    io.valid := uncovered.orR

    assert(PopCount(io.owner) <= 1.U && !(io.owner & ~uncovered).orR && io.owner.orR === io.valid,
        "advisory selection must be one oldest uncovered eligible owner, or empty")
}
