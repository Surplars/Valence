package soc.core.ooo

import chisel3._
import chisel3.util._

/** Qualification only for a known adjacent AUIPC/JALR pair, never its target data.
  * U is signed32 and J signed12, so U+J fits signed33. For an even AUIPC PC,
  * ((PC+U+J)&~1) != PC+priorLength+length iff (U+J)&~1 != priorLength+length.
  * An odd PC always differs from the even JALR target. Two low bits suffice for
  * alignment. Full64 target generation and ownership/legality remain outside.
  * Combinational II=1; no storage, queue, backpressure or extra pipeline cycle.
  */
class AuipcPredictionQualification extends Module {
    val io = IO(new Bundle {
        val auipcPcLow = Input(UInt(2.W))
        val upperImmediate = Input(UInt(32.W))
        val indirectImmediate = Input(UInt(12.W))
        val priorShort = Input(Bool())
        val shortInstruction = Input(Bool())
        val aligned16 = Output(Bool())
        val aligned32 = Output(Bool())
        val differentSuccessor = Output(Bool())
    })
    val upper = Cat(io.upperImmediate(31), io.upperImmediate).asSInt
    val indirect = Cat(Fill(21, io.indirectImmediate(11)), io.indirectImmediate).asSInt
    val delta = (upper + indirect).asUInt
    val evenDelta = Cat(delta(32, 1), 0.U(1.W))
    val successorDelta = Mux(io.priorShort, 2.U(3.W), 4.U(3.W)) +&
        Mux(io.shortInstruction, 2.U(3.W), 4.U(3.W))
    val targetLow = (io.auipcPcLow + delta(1, 0))(1, 0)
    io.aligned16 := true.B
    io.aligned32 := !targetLow(1)
    io.differentSuccessor := io.auipcPcLow(0) || evenDelta =/= successorDelta
}
