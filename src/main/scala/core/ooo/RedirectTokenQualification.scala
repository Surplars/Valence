package soc.core.ooo

import chisel3._
import chisel3.util._

/** Match full tokens before late redirect authorization; trap retains override priority.
  * Combinational, two candidates and two consumers, with no extra redirect/retire cycle.
  * Invalid payloads may be arbitrary and never authorize a consumer.
  */
class RedirectTokenQualification(p: OooParams) extends Module {
    val io = IO(new Bundle {
        val local = Input(Valid(new RobToken(p)))
        val trap = Input(Valid(new RobToken(p)))
        val queries = Input(Vec(2, new RobToken(p)))
        val matches = Output(Vec(2, Bool()))
    })
    for (consumer <- 0 until 2) {
        val localMatches = io.local.bits.asUInt === io.queries(consumer).asUInt
        val trapMatches = io.trap.bits.asUInt === io.queries(consumer).asUInt
        io.matches(consumer) := (io.trap.valid && trapMatches) ||
            (!io.trap.valid && io.local.valid && localMatches)
    }
}
