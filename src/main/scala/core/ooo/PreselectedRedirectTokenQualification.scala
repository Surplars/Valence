package soc.core.ooo

import chisel3._
import chisel3.util._

/** Default-off experiment: compare immutable raw payloads before late acceptance.
  * Acceptance selects Boolean matches, never a token feeding a wide comparison.
  * Trap overrides even when its token mismatches; system uses ACCEPTED, not request.
  * No state, changed authorization, token narrowing or extra cycle.
  */
class PreselectedRedirectTokenQualification(p: OooParams) extends Module {
    val io = IO(new Bundle {
        val localToken = Input(new RobToken(p))
        val systemToken = Input(new RobToken(p))
        val trapToken = Input(new RobToken(p))
        val localAccepted = Input(Bool())
        val systemAccepted = Input(Bool())
        val trapAccepted = Input(Bool())
        val queries = Input(Vec(2, new RobToken(p)))
        val matches = Output(Vec(2, Bool()))
    })
    for (consumer <- 0 until 2) {
        val localMatches = io.localToken.asUInt === io.queries(consumer).asUInt
        val systemMatches = io.systemToken.asUInt === io.queries(consumer).asUInt
        val trapMatches = io.trapToken.asUInt === io.queries(consumer).asUInt
        io.matches(consumer) := Mux(io.trapAccepted, trapMatches,
            Mux(io.systemAccepted, systemMatches, io.localAccepted && localMatches))
    }
}
