package soc.core.ooo

import chisel3._
import chisel3.util._

/** One fresh memory candidate plus the existing staged payload. Combinational only.
  * The caller proves resident.valid with the full live token, independently of
  * current eligibility. The only accepted start may be that resident owner.
  * Fresh source selection never depends on issued; late issued exclusion selects
  * between already available resident/fresh payloads at the existing register.
  */
class ResidentMemoryPreparationSelector(p: OooParams, predecodedHead: Boolean = false,
    val rankResidentPriority: Boolean = true, val latePoolEnable: Boolean = false,
    val directSelectedRank: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val eligible = Input(UInt(p.robEntries.W))
        val poolEnabled = if (latePoolEnable) Some(Input(Bool())) else None
        val head = Input(UInt(p.robBits.W))
        val headMask = if (predecodedHead) Some(Input(UInt(p.robEntries.W))) else None
        val resident = Flipped(Valid(UInt(p.robBits.W)))
        val issued = Input(Bool())
        val freshValid = Output(Bool())
        val freshIndex = Output(UInt(p.robBits.W))
        val freshOwner = Output(UInt(p.robEntries.W))
        val useResident = Output(Bool())
        val selectedValid = Output(Bool())
        val selectedIndex = Output(UInt(p.robBits.W))
    })
    val residentOwner = Mux(io.resident.valid, UIntToOH(io.resident.bits, p.robEntries), 0.U)
    val fresh = Module(new CircularIssueSelector(p, parallelRanks = true, predecodedHead = predecodedHead))
    // Rank the unmodified pool before the late resident full-token decision.
    // Removing at most one owner changes its oldest choice only when that
    // owner was first. The already parallel second rank is sufficient then.
    // This retains one fresh payload/PRF read group, with no new state/cycle.
    fresh.io.eligible := io.eligible
    fresh.io.head := io.head
    fresh.io.headMask.foreach(_ := io.headMask.get)
    // A disabled fallback pool must be indistinguishable from an empty pool
    // before any owner can select issue payload or physical register sources.
    val enabled = io.poolEnabled.getOrElse(true.B)
    val first = fresh.io.first & Fill(p.robEntries, enabled)
    val second = fresh.io.second & Fill(p.robEntries, enabled)
    val firstValid = fresh.io.firstValid && enabled
    val secondValid = fresh.io.secondValid && enabled
    val firstIsResident = (first & residentOwner).orR
    val freshOwner = Mux(firstIsResident, second, first)
    io.freshValid := Mux(firstIsResident, secondValid, firstValid)
    io.freshIndex := OHToUInt(freshOwner)
    io.freshOwner := freshOwner
    val residentEligible = enabled && io.resident.valid && (residentOwner & io.eligible).orR
    // The eligible resident precedes every fresh owner exactly when it is the
    // first unmodified circular rank. This also covers the sole-owner case;
    // an empty pool or invalid/ineligible resident cannot set firstIsResident.
    // Reuse the one-hot result instead of encoding both ages and comparing.
    // Keep the previous equations selectable for an exact actual-module proof.
    if (rankResidentPriority) {
        io.useResident := firstIsResident && !io.issued
    } else {
        val residentAge = io.resident.bits - io.head
        val freshAge = io.freshIndex - io.head
        io.useResident := residentEligible && !io.issued &&
            (!io.freshValid || residentAge < freshAge)
    }
    if (directSelectedRank) {
        // The selected owner is the oldest eligible rank, except when that
        // rank is the exact issued resident. Encoding the selected one-hot
        // rank avoids a second tag-dependent resident/fresh binary-index mux.
        val consumeFirst = io.issued && firstIsResident
        val selectedOwner = Mux(consumeFirst, second, first)
        io.selectedValid := Mux(consumeFirst, secondValid, firstValid)
        io.selectedIndex := OHToUInt(selectedOwner)
    } else {
        io.selectedValid := (residentEligible && !io.issued) || io.freshValid
        io.selectedIndex := Mux(io.useResident, io.resident.bits, io.freshIndex)
    }
    when(!enabled) {
        assert(first === 0.U && second === 0.U && !firstValid && !secondValid && !residentEligible,
            "disabled preparation pool must remove both ranks and resident eligibility")
        assert(io.freshOwner === 0.U && io.freshIndex === 0.U && !io.freshValid &&
            !io.useResident && !io.selectedValid && io.selectedIndex === 0.U,
            "disabled preparation pool cannot expose a phantom payload owner")
    }
    when(io.issued) {
        assert(io.resident.valid, "accepted memory start must name the caller's exact live resident")
    }
    when(io.freshValid && io.resident.valid) {
        assert(io.freshIndex =/= io.resident.bits, "fresh preparation must exclude the exact live resident")
    }
}
