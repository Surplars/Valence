package soc.core.ooo

import chisel3._
import chisel3.util._

class MultiplyDivideRequest(p: OooParams) extends Bundle {
    val token     = new RobToken(p)
    val pc        = UInt(64.W)
    val operation = UInt(3.W) // M funct3
    val word      = Bool()
    val left      = UInt(64.W)
    val right     = UInt(64.W)
}

/** Single-slot FPGA baseline: four partial products or one quotient bit per cycle. See docs/rv64m.md. */
class MultiplyDivide(p: OooParams, divisionOnly: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val start    = Flipped(Decoupled(new MultiplyDivideRequest(p)))
        val complete = Decoupled(new BackendCompletion(p))
        val cancel   = Input(Bool())
        val busy     = Output(Bool())
        val owner    = Output(new RobToken(p))
    })
    val idle :: multiply :: divide :: finish :: done :: Nil = Enum(5)
    val state                                               = RegInit(idle)
    val request                                             = Reg(new MultiplyDivideRequest(p))
    val left                                                = Reg(UInt(64.W))
    val right                                               = Reg(UInt(64.W))
    val product                                             = Reg(UInt(128.W))
    val quotient                                            = Reg(UInt(64.W))
    val remainder                                           = Reg(UInt(65.W))
    val negative                                            = Reg(Bool())
    val negativeRemainder                                   = Reg(Bool())
    val zeroDivisor                                         = Reg(Bool())
    val count                                               = Reg(UInt(7.W))
    val result                                              = Reg(UInt(64.W))
    io.start.ready := state === idle
    io.busy        := state =/= idle
    io.owner       := request.token
    // Cancellation must not feed valid: backend branch selection arbitrates this completion port.
    io.complete.valid       := state === done
    io.complete.bits        := 0.U.asTypeOf(new BackendCompletion(p))
    io.complete.bits.token  := request.token
    io.complete.bits.nextPc := request.pc + 4.U
    io.complete.bits.data   := result
    when(io.complete.fire) { state := idle }
    when(io.start.fire) {
        val op             = io.start.bits.operation
        val signedDivision = op(2) && !op(0)
        val signedLeft     = signedDivision || op === 1.U || op === 2.U
        val signedRight    = signedDivision || op === 1.U
        val a              = Mux(
            io.start.bits.word,
            Cat(Fill(32, signedLeft && io.start.bits.left(31)), io.start.bits.left(31, 0)),
            io.start.bits.left
        )
        val b = Mux(
            io.start.bits.word,
            Cat(Fill(32, signedRight && io.start.bits.right(31)), io.start.bits.right(31, 0)),
            io.start.bits.right
        )
        val negA = signedLeft && a(63)
        val negB = signedRight && b(63)
        val absA = Mux(negA, -a, a)
        val absB = Mux(negB, -b, b)
        request           := io.start.bits
        left              := absA
        right             := absB
        quotient          := absA
        remainder         := 0.U
        product           := 0.U
        negative          := negA ^ negB
        negativeRemainder := negA
        zeroDivisor       := b === 0.U
        count             := Mux(op(2), Mux(io.start.bits.word, 32.U, 64.U), 4.U)
        state             := Mux(op(2), divide, multiply)
        if (divisionOnly) {
            state := divide
            assert(op(2), "division-only specialization received multiply")
        }
        assert(!io.start.bits.word || op === 0.U || op >= 4.U, "reserved M word operation")
    }
    if (!divisionOnly) when(state === multiply) {
        product := (product << 16) + left * right(63, 48)
        right   := right << 16
        count   := count - 1.U
        when(count === 1.U) { state := finish }
    }
    when(state === divide) {
        val shifted  = Cat(remainder(63, 0), Mux(request.word, quotient(31), quotient(63)))
        val subtract = shifted >= right
        remainder := Mux(subtract, shifted - right, shifted)
        quotient  := Cat(quotient(62, 0), subtract)
        count     := count - 1.U
        when(count === 1.U) { state := finish }
    }
    when(state === finish) {
        val signedProduct   = Mux(negative, -product, product)
        val signedQuotient  = Mux(negative && !zeroDivisor, -quotient, quotient)
        val signedRemainder = Mux(negativeRemainder, -remainder(63, 0), remainder(63, 0))
        val value           =
            if (divisionOnly) Mux(request.operation(1), signedRemainder, signedQuotient)
            else
                Mux(
                    request.operation(2),
                    Mux(request.operation(1), signedRemainder, signedQuotient),
                    Mux(request.operation === 0.U, signedProduct(63, 0), signedProduct(127, 64))
                )
        result := Mux(request.word, Cat(Fill(32, value(31)), value(31, 0)), value)
        state  := done
    }
    // This wins over both a completion handshake and arithmetic state transitions.
    when(io.cancel && io.busy) { state := idle }
}
