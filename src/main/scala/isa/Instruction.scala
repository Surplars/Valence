package soc.isa

import chisel3._

/** Shared architectural encodings. No pipeline controls or platform defaults belong here. */
object Common {
    val instrNop     = "h00000013".U(32.W) // addi x0, x0, 0
    val instrIllegal = 0.U(32.W)
}

object Extension extends Enumeration {
    type Extension = Value

    val RV32I, RV64I, Zicsr               = Value
    val Zifencei                          = Value
    val S                                 = Value
    val C                                 = Value
    val Zba, Zbb, Zbs                     = Value
    val RV32M, RV32A, RV32F, RV32D, RV32Q = Value
    val RV64M, RV64A, RV64F, RV64D, RV64Q = Value
    val RV32Zfh, Zawrs                    = Value
    val RV64Zfh                           = Value
}

object Opcode {
    val OP_IMM    = "b0010011".U(7.W)
    val OP_IMM_32 = "b0011011".U(7.W) // RV64I
    val BRANCH    = "b1100011".U(7.W)
    val LOAD      = "b0000011".U(7.W)
    val STORE     = "b0100011".U(7.W)
    val MISC_MEM  = "b0001111".U(7.W)
    val SYSTEM    = "b1110011".U(7.W)
    val OP        = "b0110011".U(7.W)
    val OP_32     = "b0111011".U(7.W) // RV64I
    val JAL       = "b1101111".U(7.W)
    val JALR      = "b1100111".U(7.W)
    val LUI       = "b0110111".U(7.W)
    val AUIPC     = "b0010111".U(7.W)
    val AMO       = "b0101111".U(7.W)
}

object Funct3 {
    object I {
        val JALR = "b000".U(3.W)
        // BRANCH
        val BEQ  = "b000".U(3.W)
        val BNE  = "b001".U(3.W)
        val BLT  = "b100".U(3.W)
        val BGE  = "b101".U(3.W)
        val BLTU = "b110".U(3.W)
        val BGEU = "b111".U(3.W)
        // LOAD/STORE
        val LB  = "b000".U(3.W)
        val LH  = "b001".U(3.W)
        val LW  = "b010".U(3.W)
        val LBU = "b100".U(3.W)
        val LHU = "b101".U(3.W)
        val SB  = "b000".U(3.W)
        val SH  = "b001".U(3.W)
        val SW  = "b010".U(3.W)
        val LWU = "b110".U(3.W) // RV64I
        val LD  = "b011".U(3.W) // RV64I
        val SD  = "b011".U(3.W) // RV64I
        // OP-IMM
        val ADDI      = "b000".U(3.W)
        val SLTI      = "b010".U(3.W)
        val SLTIU     = "b011".U(3.W)
        val XORI      = "b100".U(3.W)
        val ORI       = "b110".U(3.W)
        val ANDI      = "b111".U(3.W)
        val SLLI      = "b001".U(3.W)
        val SRLI_SRAI = "b101".U(3.W)
        val ADDSUB    = "b000".U(3.W)
        val SLL       = "b001".U(3.W)
        val SLT       = "b010".U(3.W)
        val SLTU      = "b011".U(3.W)
        val XOR       = "b100".U(3.W)
        val SRL_SRA   = "b101".U(3.W)
        val OR        = "b110".U(3.W)
        val AND       = "b111".U(3.W)
        // OP-IMM-32 (RV64I)
        val ADDIW = "b000".U(3.W)
        val SLLIW = "b001".U(3.W)
        val SRLIW = "b101".U(3.W)
        val SRAIW = "b101".U(3.W)
        // OP-32 (RV64I)
        val ADDW = "b000".U(3.W)
        val SLLW = "b001".U(3.W)
        val SRLW = "b101".U(3.W)
        val SRAW = "b101".U(3.W)
    }

    object M {
        val MUL    = "b000".U(3.W)
        val MULH   = "b001".U(3.W)
        val MULHSU = "b010".U(3.W)
        val MULHU  = "b011".U(3.W)
        val DIV    = "b100".U(3.W)
        val DIVU   = "b101".U(3.W)
        val REM    = "b110".U(3.W)
        val REMU   = "b111".U(3.W)
    }

    object A {
        val W = "b010".U(3.W)
        val D = "b011".U(3.W)
    }
}

object Funct5 {
    object A {
        val LR   = "00010"
        val SC   = "00011"
        val SWAP = "00001"
        val ADD  = "00000"
        val XOR  = "00100"
        val AND  = "01100"
        val OR   = "01000"
        val MIN  = "10000"
        val MAX  = "10100"
        val MINU = "11000"
        val MAXU = "11100"
    }
}

object Funct7 {
    val Z  = "0000000"
    val NZ = "0100000"
}

object Funct6 {
    val Z  = "000000"
    val NZ = "010000"
}
