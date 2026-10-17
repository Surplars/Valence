package soc.core.inorder

import chisel3._
import chisel3.util._

class FiveStageMulDivRequest(xlen: Int) extends Bundle {
    val left = UInt(xlen.W)
    val right = UInt(xlen.W)
    val funct3 = UInt(3.W)
    val word = Bool()
}

/** Blocking EX extension, not extra architectural pipeline stages. DSP multiplication has
  * registered inputs/product/result; small profile uses shift-add. Division never uses `/` RTL.
  */
class FiveStageMulDiv(p: FiveStageConfig) extends Module {
    private val n = p.xlen
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new FiveStageMulDivRequest(n)))
        val response = Decoupled(UInt(n.W))
        val kill = Input(Bool())
        // Registered completion status, NOT permission to consume during kill.
        val completed = Output(Bool())
    })
    private val Seq(idle, multiply, combineProduct, selectProduct, iterateMultiply, divide, done) = Enum(7)
    private val state = RegInit(idle)
    private val operation = Reg(UInt(3.W))
    private val word = Reg(Bool())
    private val left = Reg(UInt(n.W))
    private val right = Reg(UInt(n.W))
    private val negativeProduct = Reg(Bool())
    private val quotientNegative = Reg(Bool())
    private val remainderNegative = Reg(Bool())
    private val zeroDivisor = Reg(Bool())
    private val quotient = Reg(UInt(n.W))
    private val remainder = Reg(UInt((n + 1).W))
    private val divisor = Reg(UInt(n.W))
    private val multiplicand = Reg(UInt((n * 2).W))
    private val accumulator = Reg(UInt((n * 2).W))
    private val count = Reg(UInt(log2Ceil(n + 1).W))
    private val result = Reg(UInt(n.W))
    def finishWord(value: UInt): UInt = if (n == 64)
        Mux(word, Cat(Fill(32, value(31)), value(31, 0)), value(n - 1, 0)) else value(31, 0)
    def selectMultiply(value: UInt): UInt =
        finishWord(Mux(operation === 0.U, value(n - 1, 0), value(n * 2 - 1, n)))
    io.request.ready := state === idle && !io.kill
    io.completed := state === done
    io.response.valid := io.completed && !io.kill
    io.response.bits := result
    when(io.request.fire) {
        val r = io.request.bits
        val division = r.funct3(2)
        val signedDivision = !r.funct3(0)
        val leftSigned = Mux(division, signedDivision, r.funct3 === 1.U || r.funct3 === 2.U)
        val rightSigned = Mux(division, signedDivision, r.funct3 === 1.U)
        val a = if (n == 64) Mux(r.word, Cat(Fill(32, leftSigned && r.left(31)), r.left(31, 0)), r.left) else r.left
        val b = if (n == 64) Mux(r.word, Cat(Fill(32, rightSigned && r.right(31)), r.right(31, 0)), r.right) else r.right
        val an = leftSigned && a(n - 1)
        val bn = rightSigned && b(n - 1)
        val absA = Mux(an, -a, a)
        val absB = Mux(bn, -b, b)
        operation := r.funct3; word := r.word; left := a; right := b
        negativeProduct := an ^ bn; quotientNegative := an ^ bn; remainderNegative := an
        zeroDivisor := b === 0.U
        divisor := absB; remainder := 0.U
        val initialDividend = if (n == 64) Mux(r.word, (absA << 32)(63, 0), absA) else absA
        quotient := Mux(division, initialDividend, absB)
        multiplicand := absA; accumulator := 0.U
        count := Mux((n == 64).B && r.word && division, 32.U, n.U)
        state := Mux(division, divide, (if (p.multiplyMode != "iterative") multiply else iterateMultiply))
    }
    if (p.multiplyMode == "dsp") {
        val product = Reg(SInt((2 * (n + 1)).W))
        val a = Cat((operation === 1.U || operation === 2.U) && left(n - 1), left).asSInt
        val b = Cat(operation === 1.U && right(n - 1), right).asSInt
        when(state === multiply) { product := a * b; state := selectProduct }
        when(state === selectProduct) { result := selectMultiply(product.asUInt); state := done }
    } else if (p.multiplyMode == "dsp-tiled") {
        // Unsigned 32x32 tiles avoid a monolithic signed 65x65 multiplier. Physical DSP count
        // is still a later Vivado mapping result, not inferred from these four operators.
        // Recombine with a carry-sized middle sum, then correct only the high half for signed
        // MULH/MULHSU. Registers are internal EX-held MDU phases, not extra CPU stages.
        val lowProduct = Reg(UInt(64.W))
        if (n == 64) {
            val crossLeft = Reg(UInt(64.W)); val crossRight = Reg(UInt(64.W))
            val highProduct = Reg(UInt(64.W))
            val unsignedLow = Reg(UInt(64.W)); val unsignedHigh = Reg(UInt(64.W))
            val signCorrection = Reg(UInt(64.W))
            when(state === multiply) {
                lowProduct := left(31, 0) * right(31, 0)
                crossLeft := left(63, 32) * right(31, 0)
                crossRight := left(31, 0) * right(63, 32)
                highProduct := left(63, 32) * right(63, 32)
                signCorrection := Mux((operation === 1.U || operation === 2.U) && left(63), right, 0.U) +
                    Mux(operation === 1.U && right(63), left, 0.U)
                state := combineProduct
            }
            val middleA = lowProduct(63, 32).pad(66)
            val middleB = crossLeft.pad(66); val middleC = crossRight.pad(66)
            // Carry-save reduction keeps the cross-term sum to one carry-propagating addition.
            val middleSum = middleA ^ middleB ^ middleC
            val middleCarry = ((middleA & middleB) | (middleA & middleC) | (middleB & middleC)) << 1
            val middle = middleSum + middleCarry(65, 0)
            when(state === combineProduct) {
                unsignedLow := Cat(middle(31, 0), lowProduct(31, 0))
                unsignedHigh := highProduct + middle(65, 32)
                state := selectProduct
            }
            when(state === selectProduct) {
                val signedHigh = unsignedHigh - signCorrection
                result := finishWord(Mux(operation === 0.U, unsignedLow, signedHigh)); state := done
            }
        } else {
            val signCorrection = Reg(UInt(32.W))
            when(state === multiply) {
                lowProduct := left * right
                signCorrection := Mux((operation === 1.U || operation === 2.U) && left(31), right, 0.U) +
                    Mux(operation === 1.U && right(31), left, 0.U)
                state := selectProduct
            }
            val high = lowProduct(63, 32) - signCorrection
            when(state === selectProduct) {
                result := Mux(operation === 0.U, lowProduct(31, 0), high); state := done
            }
        }
    } else {
        when(state === iterateMultiply) {
            val sum = accumulator + Mux(quotient(0), multiplicand, 0.U)
            accumulator := sum; multiplicand := multiplicand << 1; quotient := quotient >> 1
            count := count - 1.U
            when(count === 1.U) {
                result := selectMultiply(Mux(negativeProduct, -sum, sum)); state := done
            }
        }
    }
    when(state === divide) {
        val shifted = Cat(remainder(n - 1, 0), quotient(n - 1))
        val subtract = shifted >= divisor
        val nextRemainder = Mux(subtract, shifted - divisor, shifted)
        val nextQuotient = Cat(quotient(n - 2, 0), subtract)
        remainder := nextRemainder; quotient := nextQuotient; count := count - 1.U
        when(count === 1.U) {
            val q = Mux(zeroDivisor, Fill(n, 1.U(1.W)), Mux(quotientNegative, -nextQuotient, nextQuotient))
            val rem = Mux(zeroDivisor, left, Mux(remainderNegative, -nextRemainder(n - 1, 0), nextRemainder(n - 1, 0)))
            result := finishWord(Mux(operation(1), rem, q)); state := done
        }
    }
    when(io.response.fire) { state := idle }
    when(io.kill) { state := idle }
}
