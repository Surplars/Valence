package soc.core.ooo

import chisel3._
import chisel3.util._

/** Stateless mixed16/32 aligner over the unchanged three-packet window.
  * II 1, capacity/latency 0. Prepare fixed halfword candidates before lane1's
  * length selection. Presence authorizes validity, never instruction payload.
  */
class ParallelFetchAlignment(val width: Int) extends Module {
    require(Set(2, 4).contains(width))
    val io = IO(new Bundle {
        val packets = Input(Vec(3, UInt(64.W)))
        val present = Input(UInt(3.W))
        val errors = Input(Vec(3, UInt(2.W)))
        val pages = Input(Vec(3, UInt(2.W)))
        val pcOffset = Input(UInt(3.W))
        val instructions = Output(Vec(width, Valid(UInt(32.W))))
        val errorsOut = Output(Vec(width, Bool()))
        val pagesOut = Output(Vec(width, Bool()))
        val faultOffsets = Output(Vec(width, UInt(5.W)))
    })
    class Candidate extends Bundle {
        val present = Bool()
        val data = UInt(32.W)
        val error = Bool()
        val page = Bool()
        val faultOffset = UInt(5.W)
    }
    val candidates = (0 until 10).map { h =>
        val c = Wire(new Candidate)
        val half = io.packets(h / 4)(16 * (h % 4) + 15, 16 * (h % 4))
        val next = io.packets((h + 1) / 4)(16 * ((h + 1) % 4) + 15, 16 * ((h + 1) % 4))
        val short = half(1, 0) =/= 3.U
        val firstError = io.errors(h / 4)((h % 4) / 2)
        val firstPage = io.pages(h / 4)((h % 4) / 2)
        c.present := io.present(h / 4) && (short || io.present((h + 1) / 4))
        c.data := Cat(Mux(short, 0.U(16.W), next), half)
        c.error := firstError || (!short && io.errors((h + 1) / 4)(((h + 1) % 4) / 2))
        c.page := firstPage || (!short && io.pages((h + 1) / 4)(((h + 1) % 4) / 2))
        c.faultOffset := Mux(firstError || firstPage, (2 * h).U, (2 * h + 2).U)
        c
    }
    def at(offset: UInt): Candidate = Mux1H(
        candidates.zipWithIndex.map { case (c, h) => (offset === (2 * h).U) -> c })
    val offsets = Wire(Vec(width, UInt(5.W)))
    offsets(0) := io.pcOffset
    for (lane <- 0 until width) {
        val selected = if (lane == 1) {
            val afterShort = at(io.pcOffset.pad(5) + 2.U(5.W))
            val afterLong = at(io.pcOffset.pad(5) + 4.U(5.W))
            Mux(io.instructions(0).bits(1, 0) =/= 3.U, afterShort, afterLong)
        } else at(offsets(lane))
        io.instructions(lane).valid := selected.present
        io.instructions(lane).bits := selected.data
        io.errorsOut(lane) := selected.error
        io.pagesOut(lane) := selected.page
        io.faultOffsets(lane) := selected.faultOffset
        if (lane + 1 < width) offsets(lane + 1) := offsets(lane) +
            Mux(selected.data(1, 0) =/= 3.U, 2.U(5.W), 4.U(5.W))
    }
}
