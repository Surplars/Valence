package soc.core.ooo

import chisel3._
import chisel3.util._

/** Parallel class legality; operation priority/data semantics are unchanged.
  * Capacity 0, latency 0, II 1. B legality comes from the fixed-field decoder.
  */
class ParallelIntegerLegality(systemEnabled: Boolean, atomicEnabled: Boolean) extends Module {
    val io = IO(new Bundle {
        val instruction = Input(UInt(32.W))
        val bitLegal = Input(Bool())
        val legal = Output(Bool())
    })
    val i = io.instruction
    val op = i(6, 0)
    val f3 = i(14, 12)
    val f7 = i(31, 25)
    val immediate = op === "h13".U || op === "h1b".U
    val register = op === "h33".U || op === "h3b".U
    val word = op === "h1b".U || op === "h3b".U
    val normal = MuxLookup(f3, false.B)(Seq(
        0.U -> (immediate || f7 === 0.U || f7 === 32.U),
        1.U -> Mux(immediate && !word, i(31, 26) === 0.U, f7 === 0.U),
        2.U -> (!word && (immediate || f7 === 0.U)),
        3.U -> (!word && (immediate || f7 === 0.U)),
        4.U -> (!word && (immediate || f7 === 0.U)),
        5.U -> Mux(immediate && !word, i(31, 26) === 0.U || i(31, 26) === 16.U,
            f7 === 0.U || f7 === 32.U),
        6.U -> (!word && (immediate || f7 === 0.U)),
        7.U -> (!word && (immediate || f7 === 0.U))))
    val atomicOp = i(31, 27)
    val atomic = atomicEnabled.B && op === "h2f".U &&
        (f3 === 2.U || f3 === 3.U) &&
        Seq(0, 1, 2, 3, 4, 8, 12, 16, 20, 24, 28).map(n => atomicOp === n.U).reduce(_ || _) &&
        (atomicOp =/= 2.U || i(24, 20) === 0.U)
    val system = systemEnabled.B && (op === "h0f".U && f3 <= 1.U ||
        op === "h73".U && (Seq(1, 2, 3, 5, 6, 7).map(n => f3 === n.U).reduce(_ || _) ||
            Seq("00000073", "00100073", "30200073", "10200073", "10500073")
                .map(hex => i === ("h" + hex).U).reduce(_ || _) ||
            f7 === 9.U && i(14, 7) === 0.U))
    io.legal := io.bitLegal || atomic || system ||
        op === "h37".U || op === "h17".U || op === "h6f".U ||
        op === "h67".U && f3 === 0.U ||
        op === "h63".U && f3 =/= 2.U && f3 =/= 3.U ||
        op === "h03".U && f3 =/= 7.U || op === "h23".U && f3 <= 3.U ||
        register && f7 === 1.U && (!word || f3 === 0.U || f3 >= 4.U) ||
        op === "h33".U && f7 === 7.U && (f3 === 5.U || f3 === 7.U) ||
        (immediate || register) && normal
}
