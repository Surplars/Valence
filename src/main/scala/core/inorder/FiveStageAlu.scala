package soc.core.inorder

import chisel3._
import chisel3.util._

/** Optional FPGA masks: shared direction barrel, narrow W barrel, and early result qualification. */
class FiveStageAlu(xlen: Int, timingCuts: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val operation = Input(UInt(4.W))
        val word = Input(Bool())
        val left = Input(UInt(xlen.W))
        val right = Input(UInt(xlen.W))
        val resultEnable = if (timingCuts) Some(Input(Bool())) else None
        val result = Output(UInt(xlen.W))
    })
    val sub = io.operation === FiveStageAluOp.subtract
    val sum = if (timingCuts) I1TimingMath.add(io.left, io.right, sub, chunkBits = 16)
        else io.left + Mux(sub, ~io.right, io.right) + sub
    if (timingCuts) {
        val leftward = io.operation === FiveStageAluOp.shiftLeft
        val arithmetic = io.operation === FiveStageAluOp.shiftArithmetic
        def directionalShifts(source: UInt, amount: UInt): (UInt, UInt) = {
            val width = source.getWidth
            // Radix4 data selection: three fixed four-way layers for RV64,
            // rather than a sign/control mux followed by six binary layers.
            // Arithmetic fill depends on shift control and sign in parallel;
            // it never lengthens the late forwarded-data selection.
            def shift(left: Boolean): UInt = {
                (0 until amount.getWidth by 2).foldLeft(source) { (value, low) =>
                    val bits = math.min(2, amount.getWidth - low)
                    val choices = (0 until (1 << bits)).map { n =>
                        val distance = n << low
                        if (left) (value << distance)(width - 1, 0) else value >> distance
                    }
                    VecInit(choices.map(_.pad(width)))(amount(low + bits - 1, low))
                }
            }
            val logical = shift(left = false)
            val fill = ~(((BigInt(1) << width) - 1).U(width.W) >> amount)
            (shift(left = true), logical | (fill & Fill(width, arithmetic && source(width - 1))))
        }
        // Separate directions avoid reverse-select -> shared barrel ->
        // reverse-select after the EX producer mux. No additional edge.
        val (shiftLeft, shiftRight) = directionalShifts(io.left, io.right(log2Ceil(xlen) - 1, 0))
        // Word operations do not put a 32-bit sign/zero normalization mux
        // in front of the 64-bit barrel. Their five-bit barrel is independent.
        val (wordLeft, wordRight) = if (xlen == 64)
            directionalShifts(io.left(31, 0), io.right(4, 0)) else (shiftLeft, shiftRight)
        val unsignedLess = I1TimingMath.less(io.left, io.right)
        val signedLess = Mux(io.left(xlen - 1) =/= io.right(xlen - 1), io.left(xlen - 1), unsignedLess)
        val choices = Seq(
            (io.operation === FiveStageAluOp.add || sub, sum, sum(31, 0)),
            (leftward, shiftLeft, wordLeft),
            (io.operation === FiveStageAluOp.shiftRight || arithmetic, shiftRight, wordRight),
            (io.operation === FiveStageAluOp.lessSigned, Cat(0.U((xlen - 1).W), signedLess), Cat(0.U(31.W), signedLess)),
            (io.operation === FiveStageAluOp.lessUnsigned, Cat(0.U((xlen - 1).W), unsignedLess), Cat(0.U(31.W), unsignedLess)),
            (io.operation === FiveStageAluOp.xorBits, io.left ^ io.right, (io.left ^ io.right)(31, 0)),
            (io.operation === FiveStageAluOp.orBits, io.left | io.right, (io.left | io.right)(31, 0)),
            (io.operation === FiveStageAluOp.andBits, io.left & io.right, (io.left & io.right)(31, 0))
        ).map { case (selected, full, word) => (selected && io.resultEnable.get, full, word) }
        if (xlen == 64) {
            val low = Mux1H(choices.flatMap { case (select, full, word) =>
                Seq((select && !io.word) -> full(31, 0), (select && io.word) -> word)
            })
            val high = Mux1H(choices.map { case (select, full, _) =>
                (select && !io.word) -> full(63, 32)
            })
            val wordSign = choices.map { case (select, _, word) => select && word(31) }.reduce(_ || _)
            io.result := Cat(high | Fill(32, io.word && wordSign), low)
        } else {
            io.result := Mux1H(choices.map { case (select, full, _) => select -> full })
        }
    } else {
        // Preserve the compact/default implementation and interface semantics.
        val shift = if (xlen == 64) Mux(io.word, Cat(0.U(1.W), io.right(4, 0)), io.right(5, 0))
            else io.right(4, 0)
        val source = if (xlen == 64) Mux(io.word,
            Cat(Fill(32, io.operation === FiveStageAluOp.shiftArithmetic && io.left(31)), io.left(31, 0)), io.left)
            else io.left
        val choices = Seq(
            (io.operation === FiveStageAluOp.add || sub) -> sum,
            (io.operation === FiveStageAluOp.shiftLeft) -> (io.left << shift)(xlen - 1, 0),
            (io.operation === FiveStageAluOp.lessSigned) -> Cat(0.U((xlen - 1).W), io.left.asSInt < io.right.asSInt),
            (io.operation === FiveStageAluOp.lessUnsigned) -> Cat(0.U((xlen - 1).W), io.left < io.right),
            (io.operation === FiveStageAluOp.xorBits) -> (io.left ^ io.right),
            (io.operation === FiveStageAluOp.shiftRight) -> (source >> shift),
            (io.operation === FiveStageAluOp.shiftArithmetic) -> (source.asSInt >> shift).asUInt,
            (io.operation === FiveStageAluOp.orBits) -> (io.left | io.right),
            (io.operation === FiveStageAluOp.andBits) -> (io.left & io.right)
        )
        val result = Mux1H(choices)
        io.result := (if (xlen == 64) Mux(io.word, Cat(Fill(32, result(31)), result(31, 0)), result) else result)
    }
}
