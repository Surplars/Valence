package soc.core.ooo

import chisel3._
import chisel3.util._

/** Independent oldest-ready MUL/DIV payload owners, with late class arbitration.
  * Unit ready cannot select either operand payload. The grant is exactly the
  * oldest operation among available units, as in the combined age tournament.
  * Combinational, II=1; no added queue, result slot or multiply latency.
  */
class SplitMulDivSelector(p: OooParams, predecodedHead: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val eligible = Input(Vec(2, UInt(p.robEntries.W))) // multiply, divide
        val head = Input(UInt(p.robBits.W))
        val headMask = if (predecodedHead) Some(Input(UInt(p.robEntries.W))) else None
        val available = Input(Vec(2, Bool()))
        val owner = Output(Vec(2, UInt(p.robEntries.W)))
        val valid = Output(Vec(2, Bool()))
        val index = Output(Vec(2, UInt(p.robBits.W)))
        val grant = Output(Vec(2, Bool()))
        val selectedValid = Output(Bool())
        val selectedIndex = Output(UInt(p.robBits.W))
    })
    for (kind <- 0 until 2) {
        val selector = Module(new CircularIssueSelector(p, parallelRanks = true, predecodedHead = predecodedHead))
        selector.io.eligible := io.eligible(kind)
        selector.io.head := io.head
        selector.io.headMask.foreach(_ := io.headMask.get)
        io.owner(kind) := selector.io.first
        io.valid(kind) := selector.io.firstValid
        io.index(kind) := selector.io.firstIndex
    }
    val ages = io.index.map(_ - io.head)
    val available = (0 until 2).map(kind => io.valid(kind) && io.available(kind))
    io.grant(0) := available(0) && (!available(1) || ages(0) < ages(1))
    io.grant(1) := available(1) && (!available(0) || ages(1) < ages(0))
    io.selectedValid := available.reduce(_ || _)
    io.selectedIndex := Mux(io.grant(1), io.index(1), io.index(0))
    assert(!(io.eligible(0) & io.eligible(1)).orR, "MUL/DIV candidate classes must be disjoint")
    assert(PopCount(io.grant) === io.selectedValid.asUInt, "exactly one available M owner must win")
}
