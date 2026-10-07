package soc.core.ooo

import chisel3._

/** PC-relative prediction qualification, not target generation or branch outcome.
  * Combinational, II=1, no storage/credits/backpressure/extra cycle. Modulo-XLEN
  * addition is cancellative: PC+imm != PC+length iff imm != length, even at wrap.
  * Alignment needs only the low two bits. JALR/RAS/ITB keep their old full-target
  * qualification; faults, legality, prediction and acceptance still authorize use.
  */
class DirectPredictionQualification extends Module {
    val io = IO(new Bundle {
        val pcLow = Input(UInt(2.W))
        val immediate = Input(UInt(64.W))
        val shortInstruction = Input(Bool())
        val aligned16 = Output(Bool())
        val aligned32 = Output(Bool())
        val differentSuccessor = Output(Bool())
    })
    val targetLow = (io.pcLow + io.immediate(1, 0))(1, 0)
    io.aligned16 := !targetLow(0)
    io.aligned32 := targetLow === 0.U
    io.differentSuccessor := io.immediate =/= Mux(io.shortInstruction, 2.U, 4.U)
}
