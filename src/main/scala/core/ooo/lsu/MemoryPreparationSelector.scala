package soc.core.ooo

import chisel3._
import chisel3.util._

/** Two early candidates, one late exclusion. Combinational; no new queue or pipeline cycle.
  * Payloads for both candidates must be computed before useSecond is applied. At most
  * one prepared operation starts each cycle, so excluding that owner needs only two
  * candidates. Circular ROB age and the original head-only store eligibility are preserved.
  */
class MemoryPreparationSelector(p: OooParams, parallelRanks: Boolean = false,
    predecodedHead: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val eligible = Input(UInt(p.robEntries.W))
        val head = Input(UInt(p.robBits.W))
        val headMask = if (predecodedHead) Some(Input(UInt(p.robEntries.W))) else None
        val issued = Input(Bool())
        val issuedIndex = Input(UInt(p.robBits.W))
        val firstValid = Output(Bool())
        val firstIndex = Output(UInt(p.robBits.W))
        val secondValid = Output(Bool())
        val secondIndex = Output(UInt(p.robBits.W))
        val firstOwner = Output(UInt(p.robEntries.W))
        val secondOwner = Output(UInt(p.robEntries.W))
        val useSecond = Output(Bool())
        val selectedValid = Output(Bool())
        val selectedIndex = Output(UInt(p.robBits.W))
    })
    val afterHeadMask = io.headMask.getOrElse(VecInit((0 until p.robEntries).map(i => i.U >= io.head)).asUInt)
    def oldest(mask: UInt): UInt = {
        val afterHead = mask & afterHeadMask
        PriorityEncoderOH(Mux(afterHead.orR, afterHead, mask))
    }
    val (first, second) = if (parallelRanks) {
        val ranks = Module(new CircularIssueSelector(p, parallelRanks = true, predecodedHead = predecodedHead))
        ranks.io.eligible := io.eligible
        ranks.io.head := io.head
        ranks.io.headMask.foreach(_ := io.headMask.get)
        (ranks.io.first, ranks.io.second)
    } else {
        val first = oldest(io.eligible)
        (first, oldest(io.eligible & ~first))
    }
    val remaining = io.eligible & ~first
    io.firstOwner := first
    io.secondOwner := second
    io.firstValid := io.eligible.orR
    io.firstIndex := OHToUInt(first)
    io.secondValid := remaining.orR
    io.secondIndex := OHToUInt(second)
    io.useSecond := io.issued && io.firstValid && io.firstIndex === io.issuedIndex
    io.selectedValid := Mux(io.useSecond, io.secondValid, io.firstValid)
    io.selectedIndex := Mux(io.useSecond, io.secondIndex, io.firstIndex)
    when(io.selectedValid) {
        assert(!io.issued || io.selectedIndex =/= io.issuedIndex,
            "memory preparation must not capture the operation already issued")
    }
}
