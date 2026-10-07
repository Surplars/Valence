package soc.core.ooo

import chisel3._

/** RV64 Zba/Zbb/Zbs fixed-field legality independent of operation encoding.
  * Stateless: capacity/latency 0, II 1. Unary rs2 and RV64 shift6 fields stay strict.
  */
class ParallelBitLegality extends Module {
    val io = IO(new Bundle {
        val instruction = Input(UInt(32.W))
        val legal = Output(Bool())
    })
    val i = io.instruction
    val op = i(6, 0)
    val f3 = i(14, 12)
    val f7 = i(31, 25)
    val f6 = i(31, 26)
    val imm = i(31, 20)
    val shiftAdd = f7 === 16.U && (f3 === 2.U || f3 === 4.U || f3 === 6.U)
    val rotate = f7 === 48.U && (f3 === 1.U || f3 === 5.U)
    val register64 = op === "h33".U && (shiftAdd || rotate ||
        f7 === 32.U && (f3 === 4.U || f3 === 6.U || f3 === 7.U) ||
        f7 === 5.U && f3 >= 4.U ||
        f7 === 36.U && (f3 === 1.U || f3 === 5.U) ||
        (f7 === 20.U || f7 === 52.U) && f3 === 1.U)
    val registerWord = op === "h3b".U && (shiftAdd || rotate ||
        f7 === 4.U && (f3 === 0.U || f3 === 4.U && i(24, 20) === 0.U))
    val counts = imm === "h600".U || imm === "h601".U || imm === "h602".U
    val immediate64 = op === "h13".U && (
        f3 === 1.U && (counts || imm === "h604".U || imm === "h605".U ||
            f6 === 18.U || f6 === 10.U || f6 === 26.U) ||
        f3 === 5.U && (f6 === 24.U || f6 === 18.U ||
            imm === "h287".U || imm === "h6b8".U))
    val immediateWord = op === "h1b".U &&
        (f3 === 1.U && (counts || f6 === 2.U) || f3 === 5.U && f7 === 48.U)
    io.legal := register64 || registerWord || immediate64 || immediateWord
}
