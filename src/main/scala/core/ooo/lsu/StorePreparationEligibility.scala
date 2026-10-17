package soc.core.ooo

import chisel3._
import chisel3.util._

/** Registered owner/request facts only: no same-cycle ALU availability promise. */
class StorePreparationCandidate extends Bundle {
    val pending = Bool()
    val system = Bool()
    val mulDiv = Bool()
    val memory = Bool()
    val store = Bool()
    val prepared = Bool()
    val addressKnown = Bool()
    val usePc = Bool()
    val useImmediate = Bool()
    val operandReady1 = Bool()
    val operandReady2 = Bool()
    val controlFlow = Bool()
}

/** Exact store subset of the common issue set, computed before the late grant.
  * Zero state/latency, II=1; capacity and final authorization remain unchanged.
  * A store with no address may prepare that address before its data is ready,
  * but must not rank again with missing data once its address is already known.
  * Keeping memory-only readiness outside the common ALU mux cuts the path from
  * completion-port credit through an ALU promise into the store address adder.
  */
class StorePreparationEligibility(p: OooParams) extends Module {
    val io = IO(new Bundle {
        val entries = Input(Vec(p.robEntries, new StorePreparationCandidate))
        val head = Input(UInt(p.robBits.W))
        val branchRedirect = Input(Bool())
        val eligible = Output(UInt(p.robEntries.W))
    })
    io.eligible := VecInit((0 until p.robEntries).map { slot =>
        val entry = io.entries(slot)
        entry.pending && !entry.system && !entry.mulDiv && entry.memory && entry.store &&
            !entry.prepared && (slot.U(p.robBits.W) =/= io.head) &&
            (entry.usePc || entry.operandReady1) &&
            (entry.useImmediate || entry.operandReady2 || !entry.addressKnown) &&
            (!io.branchRedirect || !entry.controlFlow)
    }).asUInt
}
