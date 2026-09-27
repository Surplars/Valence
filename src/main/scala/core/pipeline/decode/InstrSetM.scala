package soc.core.pipeline.decode

import soc.isa._

import chisel3._

import soc.core.pipeline.ALUOps
import soc.core.pipeline.OpSel

object InstrSetM extends InstrProvider {
    def instructions: Array[InstrEntry] = Array(
        InstrEntry(
            genPat("0000001", Funct3.M.MUL, Opcode.OP),
            ALU(ALUOps.MUL, OpSel.RS1, OpSel.RS2),
            Extension.RV64M
        ),
        InstrEntry(
            genPat("0000001", Funct3.M.MULH, Opcode.OP),
            ALU(ALUOps.MULH, OpSel.RS1, OpSel.RS2),
            Extension.RV64M
        ),
        InstrEntry(
            genPat("0000001", Funct3.M.MULHSU, Opcode.OP),
            ALU(ALUOps.MULHSU, OpSel.RS1, OpSel.RS2),
            Extension.RV64M
        ),
        InstrEntry(
            genPat("0000001", Funct3.M.MULHU, Opcode.OP),
            ALU(ALUOps.MULHU, OpSel.RS1, OpSel.RS2),
            Extension.RV64M
        ),
        InstrEntry(
            genPat("0000001", Funct3.M.DIV, Opcode.OP),
            ALU(ALUOps.DIV, OpSel.RS1, OpSel.RS2),
            Extension.RV64M
        ),
        InstrEntry(
            genPat("0000001", Funct3.M.DIVU, Opcode.OP),
            ALU(ALUOps.DIVU, OpSel.RS1, OpSel.RS2),
            Extension.RV64M
        ),
        InstrEntry(
            genPat("0000001", Funct3.M.REM, Opcode.OP),
            ALU(ALUOps.REM, OpSel.RS1, OpSel.RS2),
            Extension.RV64M
        ),
        InstrEntry(
            genPat("0000001", Funct3.M.REMU, Opcode.OP),
            ALU(ALUOps.REMU, OpSel.RS1, OpSel.RS2),
            Extension.RV64M
        ),
        InstrEntry(
            genPat("0000001", Funct3.M.MUL, Opcode.OP_32),
            ALU(ALUOps.MULW, OpSel.RS1, OpSel.RS2),
            Extension.RV64M
        ),
        InstrEntry(
            genPat("0000001", Funct3.M.DIV, Opcode.OP_32),
            ALU(ALUOps.DIVW, OpSel.RS1, OpSel.RS2),
            Extension.RV64M
        ),
        InstrEntry(
            genPat("0000001", Funct3.M.DIVU, Opcode.OP_32),
            ALU(ALUOps.DIVUW, OpSel.RS1, OpSel.RS2),
            Extension.RV64M
        ),
        InstrEntry(
            genPat("0000001", Funct3.M.REM, Opcode.OP_32),
            ALU(ALUOps.REMW, OpSel.RS1, OpSel.RS2),
            Extension.RV64M
        ),
        InstrEntry(
            genPat("0000001", Funct3.M.REMU, Opcode.OP_32),
            ALU(ALUOps.REMUW, OpSel.RS1, OpSel.RS2),
            Extension.RV64M
        )
    )
}
