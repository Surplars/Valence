package soc.core.ooo

import chisel3._
import chisel3.util._

/** Pure payload selection, no grant/valid input. width candidates/cycle, no added
  * latency/state or backpressure. A fresh older lane removes its lowest free ID
  * unconditionally: any accepted later lane implies that older lane was accepted.
  * Invalid/blocked candidates never change the actual free list or RAT. Aliased
  * moves use the original ledger selector, not this fresh-register contract.
  */
class RenameDestinationCandidates(width: Int, registers: Int, parallelRanks: Boolean = false) extends Module {
    require(width >= 1 && width <= 6 && registers > 32 && registers <= 256)
    val io = IO(new Bundle {
        val free = Input(UInt(registers.W))
        val fresh = Input(UInt(width.W))
        val destination = Output(Vec(width, UInt(log2Ceil(registers).W)))
        val available = Output(UInt(width.W))
    })
    val available = Wire(Vec(width, Bool()))
    if (parallelRanks) {
        // Compute free-list ranks without any decoded fresh input. Only a narrow
        // final selection waits for the number of preceding fresh destinations.
        var remaining = io.free
        val ids = (0 until width).map { _ =>
            val first = PriorityEncoderOH(remaining)
            val id = OHToUInt(first)
            val present = remaining.orR
            remaining = remaining & ~first
            (id, present)
        }
        for (lane <- 0 until width) {
            val rank = if (lane == 0) 0.U else PopCount(io.fresh(lane - 1, 0))
            io.destination(lane) := Mux1H(ids.zipWithIndex.map { case ((id, _), k) => (rank === k.U) -> id })
            available(lane) := Mux1H(ids.zipWithIndex.map { case ((_, present), k) => (rank === k.U) -> present })
        }
    } else {
        var candidates = io.free
        for (lane <- 0 until width) {
            val first = PriorityEncoderOH(candidates)
            io.destination(lane) := OHToUInt(first)
            available(lane) := candidates.orR
            candidates = candidates & ~Mux(io.fresh(lane), first, 0.U(registers.W))
        }
    }
    io.available := available.asUInt
}
