package soc.core.ooo

import chisel3._
import chisel3.util._

class OwnerOperandAllocation(p: OooParams) extends Bundle {
    val index = UInt(p.robBits.W)
    val source1 = UInt(p.physBits.W)
    val source2 = UInt(p.physBits.W)
}

/** Owner-local mirrors of the registered physical ready file, not an extra wakeup stage.
  * Both files consume the SAME accepted wake/reserve events at the same edge; reserve
  * wins. Allocation reads the next physical state, including same-packet RAW and
  * move aliases, while inactive/undefined queue sources never index the compact PRF.
  * Two bits per ROB owner replace a source-ID mux on memory/M scheduling paths.
  * No capacity, acceptance, issue latency or speculative ALU-forwarding change.
  */
class OwnerOperandReady(p: OooParams, precomputedAllocationReady: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val physical = Input(UInt(p.physicalRegs.W))
        val active = Input(UInt(p.robEntries.W))
        val source1 = Input(Vec(p.robEntries, UInt(p.physBits.W)))
        val source2 = Input(Vec(p.robEntries, UInt(p.physBits.W)))
        val wake = Input(Vec(p.completionWidth + 1, Valid(UInt(p.physBits.W))))
        val reserve = Input(Vec(p.renameWidth, Valid(UInt(p.physBits.W))))
        val allocate = Input(Vec(p.renameWidth, Valid(new OwnerOperandAllocation(p))))
        val allocationReady1 = if (precomputedAllocationReady) Some(Input(Vec(p.renameWidth, Bool()))) else None
        val allocationReady2 = if (precomputedAllocationReady) Some(Input(Vec(p.renameWidth, Bool()))) else None
        val executionClass = if (p.registeredLoadResultReady) Some(Input(Vec(p.robEntries, Bool()))) else None
        val allocationExecutionClass = if (p.registeredLoadResultReady)
            Some(Input(Vec(p.renameWidth, Bool()))) else None
        val heldLoads = if (p.registeredLoadResultReady)
            Some(Input(Vec(p.memoryEntries, Valid(UInt(p.physBits.W))))) else None
        val publishedLoads = if (p.registeredLoadResultReady)
            Some(Input(Vec(p.memoryEntries, Valid(UInt(p.physBits.W))))) else None
        val ready1 = Output(Vec(p.robEntries, Bool()))
        val ready2 = Output(Vec(p.robEntries, Bool()))
    })
    val ready1 = RegInit(VecInit(Seq.fill(p.robEntries)(false.B)))
    val ready2 = RegInit(VecInit(Seq.fill(p.robEntries)(false.B)))
    def physical(index: UInt): Bool = (0 until p.physicalRegs)
        .map(r => index === r.U && io.physical(r)).reduce(_ || _)
    def held(index: UInt): Bool = io.heldLoads.map(loads =>
        loads.map(h => h.valid && h.bits === index).reduce(_ || _)).getOrElse(false.B)
    def published(index: UInt): Bool = io.publishedLoads.map(loads =>
        loads.map(h => h.valid && h.bits === index).reduce(_ || _)).getOrElse(false.B)
    def oldExecution(slot: Int): Bool = io.executionClass.map(_(slot)).getOrElse(false.B)
    def newExecution(lane: Int): Bool = io.allocationExecutionClass.map(_(lane)).getOrElse(false.B)
    def updated(current: Bool, index: UInt, execution: Bool = false.B): Bool = {
        val waking = io.wake.map(w => w.valid && w.bits === index).reduce(_ || _)
        val reserving = io.reserve.map(r => r.valid && r.bits === index).reduce(_ || _)
        if (p.registeredLoadResultReady) (current || waking || (execution && published(index))) && !reserving
        else (current || waking) && !reserving
    }
    def allocated(index: UInt, lane: Int): Bool = {
        val base = if (p.registeredLoadResultReady) physical(index) || (newExecution(lane) && held(index))
            else physical(index)
        updated(base, index, newExecution(lane))
    }
    // One next-state initialization per incoming lane/source, not a replica per
    // destination ROB slot. Acceptance/index matching remains the late write
    // enable below; wake/reserve and reserve-over-wake priority are unchanged.
    val allocationReady1 = io.allocationReady1.getOrElse(VecInit(io.allocate.zipWithIndex.map { case (incoming, lane) =>
        allocated(incoming.bits.source1, lane) }))
    val allocationReady2 = io.allocationReady2.getOrElse(VecInit(io.allocate.zipWithIndex.map { case (incoming, lane) =>
        allocated(incoming.bits.source2, lane) }))
    for (slot <- 0 until p.robEntries) {
        when(io.active(slot)) {
            ready1(slot) := updated(ready1(slot), io.source1(slot), oldExecution(slot))
            ready2(slot) := updated(ready2(slot), io.source2(slot), oldExecution(slot))
            assert(io.source1(slot) < p.physicalRegs.U && io.source2(slot) < p.physicalRegs.U,
                "active operand-ready owner must contain valid physical source IDs")
            if (p.registeredLoadResultReady) {
                assert(ready1(slot) === (physical(io.source1(slot)) || (oldExecution(slot) && held(io.source1(slot)))) &&
                    ready2(slot) === (physical(io.source2(slot)) || (oldExecution(slot) && held(io.source2(slot)))),
                    "both owner-ready sources equal physical data or a class-qualified stable load holder")
            } else {
                assert(ready1(slot) === physical(io.source1(slot)) &&
                    ready2(slot) === physical(io.source2(slot)),
                    "owner-local readiness must equal the registered physical ready file")
            }
        }
        for (lane <- 0 until p.renameWidth) {
            val incoming = io.allocate(lane)
            when(incoming.valid && incoming.bits.index === slot.U) {
                ready1(slot) := allocationReady1(lane)
                ready2(slot) := allocationReady2(lane)
                assert(incoming.bits.source1 < p.physicalRegs.U && incoming.bits.source2 < p.physicalRegs.U,
                    "new operand-ready owner must contain valid physical source IDs")
                if (precomputedAllocationReady) {
                    assert(allocationReady1(lane) === allocated(incoming.bits.source1, lane) &&
                        allocationReady2(lane) === allocated(incoming.bits.source2, lane),
                        "precomputed allocation readiness must equal the same accepted wake/reserve next state")
                }
            }
        }
    }
    io.ready1 := ready1
    io.ready2 := ready2
}
