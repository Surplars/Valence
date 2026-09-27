package soc.core.pipeline.decode

import soc.isa._

import chisel3._

import soc.core.pipeline.ALUOps
import soc.core.pipeline.OpSel
import soc.core.pipeline.BranchType
import chisel3.util.BitPat

object InstrSetI extends InstrProvider {
    def instructions: Array[InstrEntry] = Array(
        InstrEntry( // LUI
            genPat(Opcode.LUI),
            ALU(ALUOps.ADD, OpSel.ZERO, OpSel.IMM),
            Extension.RV64I
        ),
        InstrEntry( // AUIPC
            genPat(Opcode.AUIPC),
            ALU(ALUOps.ADD, OpSel.PC, OpSel.IMM),
            Extension.RV64I
        ),
        InstrEntry( // JAL
            genPat(Opcode.JAL),
            ALU(ALUOps.ADD, OpSel.PC, OpSel.IMM, brType = BranchType.JAL),
            Extension.RV64I
        ),
        InstrEntry( // JALR
            genPat(Opcode.JALR),
            ALU(ALUOps.ADD, OpSel.RS1, OpSel.IMM, brType = BranchType.JALR),
            Extension.RV64I
        ),
        InstrEntry( // BEQ
            genPat(Funct3.I.BEQ, Opcode.BRANCH),
            BR(BranchType.BEQ),
            Extension.RV64I
        ),
        InstrEntry( // BNE
            genPat(Funct3.I.BNE, Opcode.BRANCH),
            BR(BranchType.BNE),
            Extension.RV64I
        ),
        InstrEntry( // BLT
            genPat(Funct3.I.BLT, Opcode.BRANCH),
            BR(BranchType.BLT),
            Extension.RV64I
        ),
        InstrEntry( // BGE
            genPat(Funct3.I.BGE, Opcode.BRANCH),
            BR(BranchType.BGE),
            Extension.RV64I
        ),
        InstrEntry( // BLTU
            genPat(Funct3.I.BLTU, Opcode.BRANCH),
            BR(BranchType.BLTU),
            Extension.RV64I
        ),
        InstrEntry( // BGEU
            genPat(Funct3.I.BGEU, Opcode.BRANCH),
            BR(BranchType.BGEU),
            Extension.RV64I
        ),
        InstrEntry( // LB
            genPat(Funct3.I.LB, Opcode.LOAD),
            MEM(true, OpSel.RS1, OpSel.IMM, ALUOps.ADD),
            Extension.RV64I
        ),
        InstrEntry( // LH
            genPat(Funct3.I.LH, Opcode.LOAD),
            MEM(true, OpSel.RS1, OpSel.IMM, ALUOps.ADD),
            Extension.RV64I
        ),
        InstrEntry( // LW
            genPat(Funct3.I.LW, Opcode.LOAD),
            MEM(true, OpSel.RS1, OpSel.IMM, ALUOps.ADD),
            Extension.RV64I
        ),
        InstrEntry( // LBU
            genPat(Funct3.I.LBU, Opcode.LOAD),
            MEM(true, OpSel.RS1, OpSel.IMM, ALUOps.ADD),
            Extension.RV64I
        ),
        InstrEntry( // LHU
            genPat(Funct3.I.LHU, Opcode.LOAD),
            MEM(true, OpSel.RS1, OpSel.IMM, ALUOps.ADD),
            Extension.RV64I
        ),
        InstrEntry( // SB
            genPat(Funct3.I.SB, Opcode.STORE),
            MEM(false, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        ),
        InstrEntry( // SH
            genPat(Funct3.I.SH, Opcode.STORE),
            MEM(false, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        ),
        InstrEntry( // SW
            genPat(Funct3.I.SW, Opcode.STORE),
            MEM(false, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        ),
        InstrEntry( // ADDI
            genPat(Funct3.I.ADDI, Opcode.OP_IMM),
            ALU(ALUOps.ADD, OpSel.RS1, OpSel.IMM),
            Extension.RV64I
        ),
        InstrEntry( // SLTI
            genPat(Funct3.I.SLTI, Opcode.OP_IMM),
            ALU(ALUOps.SLT, OpSel.RS1, OpSel.IMM),
            Extension.RV64I
        ),
        InstrEntry( // SLTIU
            genPat(Funct3.I.SLTIU, Opcode.OP_IMM),
            ALU(ALUOps.SLTU, OpSel.RS1, OpSel.IMM),
            Extension.RV64I
        ),
        InstrEntry( // XORI
            genPat(Funct3.I.XORI, Opcode.OP_IMM),
            ALU(ALUOps.XOR, OpSel.RS1, OpSel.IMM),
            Extension.RV64I
        ),
        InstrEntry( // ORI
            genPat(Funct3.I.ORI, Opcode.OP_IMM),
            ALU(ALUOps.OR, OpSel.RS1, OpSel.IMM),
            Extension.RV64I
        ),
        InstrEntry( // ANDI
            genPat(Funct3.I.ANDI, Opcode.OP_IMM),
            ALU(ALUOps.AND, OpSel.RS1, OpSel.IMM),
            Extension.RV64I
        ),
        InstrEntry( // SLLI
            genPatShiftImm64(Funct6.Z, Funct3.I.SLLI, Opcode.OP_IMM),
            ALU(ALUOps.SLL, OpSel.RS1, OpSel.IMM),
            Extension.RV64I
        ),
        InstrEntry( // SRLI
            genPatShiftImm64(Funct6.Z, Funct3.I.SRLI_SRAI, Opcode.OP_IMM),
            ALU(ALUOps.SRL, OpSel.RS1, OpSel.IMM),
            Extension.RV64I
        ),
        InstrEntry( // SRAI
            genPatShiftImm64(Funct6.NZ, Funct3.I.SRLI_SRAI, Opcode.OP_IMM),
            ALU(ALUOps.SRA, OpSel.RS1, OpSel.IMM),
            Extension.RV64I
        ),
        InstrEntry( // ADD
            genPat(Funct7.Z, Funct3.I.ADDSUB, Opcode.OP),
            ALU(ALUOps.ADD, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        ),
        InstrEntry( // SUB
            genPat(Funct7.NZ, Funct3.I.ADDSUB, Opcode.OP),
            ALU(ALUOps.SUB, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        ),
        InstrEntry( // SLL
            genPat(Funct7.Z, Funct3.I.SLL, Opcode.OP),
            ALU(ALUOps.SLL, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        ),
        InstrEntry( // SLT
            genPat(Funct7.Z, Funct3.I.SLT, Opcode.OP),
            ALU(ALUOps.SLT, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        ),
        InstrEntry( // SLTU
            genPat(Funct7.Z, Funct3.I.SLTU, Opcode.OP),
            ALU(ALUOps.SLTU, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        ),
        InstrEntry( // XOR
            genPat(Funct7.Z, Funct3.I.XOR, Opcode.OP),
            ALU(ALUOps.XOR, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        ),
        InstrEntry( // SRL
            genPat(Funct7.Z, Funct3.I.SRL_SRA, Opcode.OP),
            ALU(ALUOps.SRL, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        ),
        InstrEntry( // SRA
            genPat(Funct7.NZ, Funct3.I.SRL_SRA, Opcode.OP),
            ALU(ALUOps.SRA, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        ),
        InstrEntry( // OR
            genPat(Funct7.Z, Funct3.I.OR, Opcode.OP),
            ALU(ALUOps.OR, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        ),
        InstrEntry( // AND
            genPat(Funct7.Z, Funct3.I.AND, Opcode.OP),
            ALU(ALUOps.AND, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        ),
        InstrEntry( // ECALL
            BitPat("b0000000_00000_00000_000_00000_1110011"),
            ALU(ALUOps.NOP, OpSel.ZERO, OpSel.ZERO, brType = BranchType.ECALL),
            Extension.RV64I
        ),
        InstrEntry( // EBREAK
            BitPat("b0000000_00001_00000_000_00000_1110011"),
            ALU(ALUOps.NOP, OpSel.ZERO, OpSel.ZERO, brType = BranchType.EBREAK),
            Extension.RV64I
        ),
        // RV64I
        InstrEntry( // LWU
            genPat(Funct3.I.LWU, Opcode.LOAD),
            MEM(true, OpSel.RS1, OpSel.IMM, ALUOps.ADD),
            Extension.RV64I
        ),
        InstrEntry( // LD
            genPat(Funct3.I.LD, Opcode.LOAD),
            MEM(true, OpSel.RS1, OpSel.IMM, ALUOps.ADD),
            Extension.RV64I
        ),
        InstrEntry( // SD
            genPat(Funct3.I.SD, Opcode.STORE),
            MEM(false, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        ),
        InstrEntry( // FENCE
            BitPat("b???????_?????_?????_000_?????_0001111"),
            ALU(ALUOps.NOP, OpSel.ZERO, OpSel.ZERO, writeReg = false),
            Extension.RV64I
        ),
        InstrEntry( // ADDIW
            genPat(Funct3.I.ADDIW, Opcode.OP_IMM_32),
            ALU(ALUOps.ADDW, OpSel.RS1, OpSel.IMM),
            Extension.RV64I
        ),
        InstrEntry( // SLLIW
            genPat(Funct7.Z, Funct3.I.SLLIW, Opcode.OP_IMM_32),
            ALU(ALUOps.SLLW, OpSel.RS1, OpSel.IMM),
            Extension.RV64I
        ),
        InstrEntry( // SRLIW
            genPat(Funct7.Z, Funct3.I.SRLIW, Opcode.OP_IMM_32),
            ALU(ALUOps.SRLW, OpSel.RS1, OpSel.IMM),
            Extension.RV64I
        ),
        InstrEntry( // SRAIW
            genPat(Funct7.NZ, Funct3.I.SRAIW, Opcode.OP_IMM_32),
            ALU(ALUOps.SRAW, OpSel.RS1, OpSel.IMM),
            Extension.RV64I
        ),
        InstrEntry( // ADDW
            genPat(Funct7.Z, Funct3.I.ADDW, Opcode.OP_32),
            ALU(ALUOps.ADDW, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        ),
        InstrEntry( // SUBW
            genPat(Funct7.NZ, Funct3.I.ADDW, Opcode.OP_32),
            ALU(ALUOps.SUBW, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        ),
        InstrEntry( // SLLW
            genPat(Funct7.Z, Funct3.I.SLLW, Opcode.OP_32),
            ALU(ALUOps.SLLW, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        ),
        InstrEntry( // SRLW
            genPat(Funct7.Z, Funct3.I.SRLW, Opcode.OP_32),
            ALU(ALUOps.SRLW, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        ),
        InstrEntry( // SRAW
            genPat(Funct7.NZ, Funct3.I.SRAW, Opcode.OP_32),
            ALU(ALUOps.SRAW, OpSel.RS1, OpSel.RS2),
            Extension.RV64I
        )
    )
}
