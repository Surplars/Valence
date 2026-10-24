package soc.core.ooo

import chisel3._
import chisel3.util._

/** Two work-conserving completion ports over independently held producer owners.
  *
  * Inputs are registered producer presence and ROB slot identity, never an ALU
  * result, downstream acceptance, recovery decision, or issue grant. Both ranks
  * are computed independently. Selection adds no state or completion latency;
  * producer-local elastic state owns all payload/backpressure. Sustains two
  * distinct owners per cycle. Full generation/liveness/fault authorization stays
  * in RenameRob, after payload selection. An identical slot offered twice is
  * conservatively represented once, with lower producer number as tie breaker.
  */
class DualCompletionSelector(p: OooParams, producers: Int = 6) extends Module {
    require(p.completionWidth == 2 && producers >= 2)
    val io = IO(new Bundle {
        val head = Input(UInt(p.robBits.W))
        val present = Input(UInt(producers.W))
        val index = Input(Vec(producers, UInt(p.robBits.W)))
        val owners = Output(Vec(2, UInt(producers.W)))
        val selected = Output(UInt(producers.W))
    })
    val age = io.index.map(index => (index - io.head)(p.robBits - 1, 0))
    val unique = (0 until producers).map { i =>
        io.present(i) && !(0 until i).map(j => io.present(j) && io.index(j) === io.index(i))
            .foldLeft(false.B)(_ || _)
    }
    val earlier = (0 until producers).map { i =>
        PopCount((0 until producers).filter(_ != i).map(j => unique(j) && age(j) < age(i)))
    }
    for (rank <- 0 until 2) {
        io.owners(rank) := VecInit((0 until producers).map(i => unique(i) && earlier(i) === rank.U)).asUInt
        assert(PopCount(io.owners(rank)) <= 1.U, "one producer per completion write port")
    }
    io.selected := io.owners.reduce(_ | _)
    assert(!(io.owners(0) & io.owners(1)).orR, "one producer cannot consume two completion ports")
    assert(PopCount(io.selected) === Mux(PopCount(unique) >= 2.U, 2.U, PopCount(unique)),
        "every available completion port must service a distinct offered owner")
}
