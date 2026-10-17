package soc.core.ooo

import chisel3._
import chisel3.util._
import hardfloat.{AddRawFN, RoundRawFNToRecFN, fNFromRecFN, rawFloatFromRecFN, recFNFromFN}

/** First arithmetic producer: FADD.S / FSUB.S only, using pinned HardFloat.
  * One transaction, capacity one, latency two cycles, minimum II=3.
  * No same-cycle refill. Flush suppresses acceptance and discards held results.
  * Full IEEE/boxed operands enter and boxed IEEE results leave; recFN stays local.
  * Rounding must already be resolved (0..4). Other operations return illegal.
  * Register the raw normalized result before rounding. Full token and resolved
  * rounding travel with that stage; no vendor source changes or timing exceptions.
  */
class FloatingPointAdd(p: OooParams) extends Module {
    val io = IO(new Bundle {
        val flush = Input(Bool())
        val request = Flipped(Decoupled(new FloatingPointExecution(p)))
        val result = Decoupled(new FloatingPointResult(p))
    })
    val occupied = RegInit(false.B)
    val rawValid = RegInit(false.B)
    val result = Reg(new FloatingPointResult(p))
    io.request.ready := !occupied && !rawValid && !io.flush
    io.result.valid := occupied && !io.flush
    io.result.bits := result

    val instruction = io.request.bits.command.instruction
    val supported = instruction(6, 0) === "b1010011".U &&
        (instruction(31, 25) === 0.U || instruction(31, 25) === 4.U)
    val legal = supported && io.request.bits.rounding <= 4.U
    val add = Module(new AddRawFN(8, 24))
    add.io.a := rawFloatFromRecFN(8, 24,
        recFNFromFN(8, 24, FloatingPointBits.operand(io.request.bits.operands(0), true.B)(31, 0)))
    add.io.b := rawFloatFromRecFN(8, 24,
        recFNFromFN(8, 24, FloatingPointBits.operand(io.request.bits.operands(1), true.B)(31, 0)))
    add.io.subOp := instruction(27)
    add.io.roundingMode := io.request.bits.rounding
    val raw = Reg(chiselTypeOf(add.io.rawOut))
    val invalid = Reg(Bool())
    val rounding = Reg(UInt(3.W))
    val pendingLegal = Reg(Bool())
    val round = Module(new RoundRawFNToRecFN(8, 24, 0))
    round.io.in := raw
    round.io.invalidExc := invalid
    round.io.infiniteExc := false.B
    round.io.roundingMode := rounding
    round.io.detectTininess := true.B // RISC-V: detect tininess after rounding.
    val ieee = fNFromRecFN(8, 24, round.io.out)
    val isNaN = ieee(30, 23).andR && ieee(22, 0).orR
    val canonical = Mux(isNaN, "h7fc00000".U(32.W), ieee)
    when(io.request.fire) {
        rawValid := true.B
        raw := add.io.rawOut
        invalid := add.io.invalidExc
        rounding := io.request.bits.rounding
        pendingLegal := legal
        result.token := io.request.bits.command.token
        result.exception := !legal
        result.cause := Mux(legal, 0.U, 2.U)
        result.tval := Mux(legal, 0.U, instruction.pad(64))
    }
    when(rawValid) {
        rawValid := false.B
        occupied := true.B
        result.value := Mux(pendingLegal, FloatingPointBits.boxSingle(canonical), 0.U)
        result.flags := Mux(pendingLegal, round.io.exceptionFlags, 0.U)
    }
    when(io.result.fire) { occupied := false.B }
    when(io.flush) { occupied := false.B; rawValid := false.B }
    assert(!(rawValid && occupied), "FP add capacity one spans both stages")
}
