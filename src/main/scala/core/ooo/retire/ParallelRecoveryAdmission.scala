package soc.core.ooo

import chisel3._
import chisel3.util._

/** Combinational two-candidate recovery admission. No queue, cycle or ownership shortcut.
  * Both original candidates are checked before selection; external admission and the
  * original age/tie priority select a candidate even when the local token is stale.
  * Full allocation tags remain authoritative. Per-slot discard/retention is computed
  * from the two original boundaries rather than from the late selected token.
  */
class ParallelRecoveryAdmission(p: OooParams) extends Module {
    val io = IO(new Bundle {
        val head = Input(UInt(p.robBits.W))
        val count = Input(UInt(p.countBits.W))
        val tags = Input(Vec(p.robEntries, UInt(p.tagBits.W)))
        val recovering = Input(Bool())
        val keepCount = Input(UInt(p.countBits.W))
        val external = Input(Valid(new RecoveryRequest(p)))
        val local = Input(Valid(new RecoveryRequest(p)))
        val externalAccepted = Output(Bool())
        val externalWins = Output(Bool())
        val selected = Output(Valid(new RecoveryRequest(p)))
        val accepted = Output(Bool())
        val activeKeep = Output(UInt(p.countBits.W))
        val killed = Output(UInt(p.robEntries.W))
        val survives = Output(UInt(p.robEntries.W))
    })
    def age(index: UInt): UInt = (index - io.head)(p.robBits - 1, 0)
    val externalAge = age(io.external.bits.token.index)
    val localAge = age(io.local.bits.token.index)
    val externalKeep = externalAge.pad(p.countBits) + !io.external.bits.inclusive
    val localKeep = localAge.pad(p.countBits) + !io.local.bits.inclusive
    def admissible(request: ValidIO[RecoveryRequest], tokenAge: UInt, keep: UInt): Bool =
        request.valid && tokenAge < io.count && io.tags(request.bits.token.index) === request.bits.token.tag &&
            (!io.recovering || keep < io.keepCount)
    val externalAccepted = admissible(io.external, externalAge, externalKeep)
    val localAccepted = admissible(io.local, localAge, localKeep)
    val externalWins = externalAccepted && (!io.local.valid || externalAge <= localAge)
    val accepted = externalWins || localAccepted
    io.externalAccepted := externalAccepted
    io.externalWins := externalWins
    io.selected.valid := externalWins || io.local.valid
    io.selected.bits := Mux(externalWins, io.external.bits, io.local.bits)
    io.accepted := accepted
    io.activeKeep := Mux(accepted, Mux(externalWins, externalKeep, localKeep), io.keepCount)
    val killed = Wire(Vec(p.robEntries, Bool()))
    val survives = Wire(Vec(p.robEntries, Bool()))
    for (slot <- 0 until p.robEntries) {
        val slotAge = age(slot.U(p.robBits.W))
        val retainedByNewBoundary = Mux(externalWins, slotAge < externalKeep, slotAge < localKeep)
        killed(slot) := accepted && !retainedByNewBoundary
        survives(slot) := Mux(accepted, retainedByNewBoundary,
            !io.recovering || slotAge < io.keepCount)
    }
    io.killed := killed.asUInt
    io.survives := survives.asUInt
}

/** Optional ledger interface; the ledger owns arbitration and the selected boundary. */
class ParallelRecoveryPort(p: OooParams) extends Bundle {
    val local = Input(Valid(new RecoveryRequest(p)))
    val externalWins = Output(Bool())
    val selected = Output(Valid(new RecoveryRequest(p)))
    val killed = Output(UInt(p.robEntries.W))
}

/** Trusted local trap request, not an arbitrary recovery-token interface.
  * The producer has already established the architectural safe-trap boundary.
  * The ledger owns the current head, so this request ALWAYS means inclusive
  * rollback to zero retained instructions. No supplied token can bypass checks.
  * General external/branch requests must still use ParallelRecoveryAdmission.
  */
class HeadTrapRecoveryPort extends Bundle {
    val valid = Input(Bool())
    val accepted = Output(Bool())
}
