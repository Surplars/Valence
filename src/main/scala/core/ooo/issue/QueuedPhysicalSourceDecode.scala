package soc.core.ooo

import chisel3._
import chisel3.util._

/** Shared, pure queued-source equality decode, not a physical-register read port.
  * No owner/grant/kill/readiness/value input, storage, capacity or backpressure.
  * Every consumer retains independent two-owner/four-value-read networks.
  * Stale unselected IDs outside a compact PRF simply produce zero matches.
  * Higher shared fanout is a physical-design tradeoff, not an assumed area gain.
  */
class QueuedPhysicalSourceDecode(p: OooParams) extends Module {
    val io = IO(new Bundle {
        val source1 = Input(Vec(p.robEntries, UInt(p.physBits.W)))
        val source2 = Input(Vec(p.robEntries, UInt(p.physBits.W)))
        val decoded1 = Output(Vec(p.physicalRegs, UInt(p.robEntries.W)))
        val decoded2 = Output(Vec(p.physicalRegs, UInt(p.robEntries.W)))
    })
    for (physical <- 0 until p.physicalRegs) {
        io.decoded1(physical) := VecInit(io.source1.map(_ === physical.U)).asUInt
        io.decoded2(physical) := VecInit(io.source2.map(_ === physical.U)).asUInt
    }
}
