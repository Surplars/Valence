package soc.core.ooo

import chisel3._
import chisel3.util._

/** Only architectural control-flow/AUIPC predecode, not execution legality.
  * Input is the canonical instruction after existing compressed expansion and
  * reserved-compressed suppression. Unrelated ALU/M/B/CSR legality must not sit
  * on the prediction path. The full decoder still authorizes allocation/traps.
  * Combinational II=1, no storage, capacity, backpressure or extra cycle.
  */
class FrontendControlDecode extends Module {
    val io = IO(new Bundle {
        val instruction = Input(UInt(32.W))
        val auipc = Output(Bool())
        val conditional = Output(Bool())
        val direct = Output(Bool())
        val indirect = Output(Bool())
        val rd = Output(UInt(5.W))
        val rs1 = Output(UInt(5.W))
        val immediate = Output(UInt(64.W))
    })
    val instruction = io.instruction
    val opcode = instruction(6, 0)
    val funct3 = instruction(14, 12)
    io.auipc := opcode === "h17".U
    io.direct := opcode === "h6f".U
    io.indirect := opcode === "h67".U && funct3 === 0.U
    io.conditional := opcode === "h63".U && (funct3 === 0.U || funct3 === 1.U || funct3 >= 4.U)
    io.rd := instruction(11, 7)
    io.rs1 := instruction(19, 15)
    val upper = Cat(Fill(32, instruction(31)), instruction(31, 12), 0.U(12.W))
    val jump = Cat(Fill(43, instruction(31)), instruction(31), instruction(19, 12),
        instruction(20), instruction(30, 21), 0.U(1.W))
    val branch = Cat(Fill(51, instruction(31)), instruction(31), instruction(7),
        instruction(30, 25), instruction(11, 8), 0.U(1.W))
    val indirect = Cat(Fill(52, instruction(31)), instruction(31, 20))
    io.immediate := Mux1H(Seq(io.auipc -> upper, io.direct -> jump,
        io.conditional -> branch, io.indirect -> indirect))
}
