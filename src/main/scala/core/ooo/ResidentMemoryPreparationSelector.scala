package soc.core.ooo

import chisel3._
import chisel3.util._

/** One fresh memory candidate plus the existing staged payload. Combinational only.
  * The caller proves resident.valid with the full live token, independently of
  * current eligibility. The only accepted start may be that resident owner.
  * Fresh source selection never depends on issued; late issued exclusion selects
  * between already available resident/fresh payloads at the existing register.
  */
class ResidentMemoryPreparationSelector(p: OooParams, predecodedHead: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val eligible = Input(UInt(p.robEntries.W))
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
    fresh.io.eligible := io.eligible & ~residentOwner
    fresh.io.head := io.head
    fresh.io.headMask.foreach(_ := io.headMask.get)
    io.freshValid := fresh.io.firstValid
    io.freshIndex := fresh.io.firstIndex
    io.freshOwner := fresh.io.first
    val residentEligible = io.resident.valid && (residentOwner & io.eligible).orR
    val residentAge = io.resident.bits - io.head
    val freshAge = fresh.io.firstIndex - io.head
    io.useResident := residentEligible && !io.issued &&
        (!fresh.io.firstValid || residentAge < freshAge)
    io.selectedValid := (residentEligible && !io.issued) || fresh.io.firstValid
    io.selectedIndex := Mux(io.useResident, io.resident.bits, fresh.io.firstIndex)
    when(io.issued) {
        assert(io.resident.valid, "accepted memory start must name the caller's exact live resident")
    }
    when(io.freshValid && io.resident.valid) {
        assert(io.freshIndex =/= io.resident.bits, "fresh preparation must exclude the exact live resident")
    }
}
