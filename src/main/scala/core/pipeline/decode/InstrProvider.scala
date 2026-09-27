package soc.core.pipeline.decode

import chisel3._
import chisel3.util._
import soc.isa._
import soc.core.pipeline.{ALUOps, BranchType, CSROps, OpSel}

/** Legacy in-order control adapter. Standard ISA definitions must not depend on this package. */
trait InstrProvider {
    val Y = true.B
    val N = false.B

    // List(valid, op1sel, op2sel, ALUOps, reg_write, mem_read, mem_write, CSROps, BranchType)
    // 普通 ALU 指令 不需要 Mem, CSR, Branch
    def ALU(
        op: ALUOps.Type,
        op1: OpSel.Type,
        op2: OpSel.Type,
        mem_read: Boolean = false,
        mem_write: Boolean = false,
        writeReg: Boolean = true,
        brType: BranchType.Type = BranchType.None
    ): List[Data] = {
        List(Y, op1, op2, op, writeReg.B, mem_read.B, mem_write.B, CSROps.None, brType)
    }
    // 内存访问指令
    def MEM(isLoad: Boolean, op1: OpSel.Type, op2: OpSel.Type, op: ALUOps.Type = ALUOps.NOP): List[Data] = {
        List(Y, op1, op2, op, isLoad.B, isLoad.B, (!isLoad).B, CSROps.None, BranchType.None)
    }
    // 分支指令
    def BR(brType: BranchType.Type): List[Data] = {
        List(Y, OpSel.RS1, OpSel.RS2, ALUOps.NOP, N, N, N, CSROps.None, brType)
    }
    // CSR指令
    def CSR(csrOp: CSROps.Type): List[Data] = {
        List(Y, OpSel.CSR, OpSel.RS1, ALUOps.NOP, Y, N, N, csrOp, BranchType.None)
    }
    def ATOMIC: List[Data] = {
        List(Y, OpSel.RS1, OpSel.RS2, ALUOps.NOP, Y, N, N, CSROps.None, BranchType.None)
    }

    def UStr(u: UInt, width: Int): String = {
        // u.litValue 获取 BigInt, toString(2) 转二进制
        val s = u.litValue.toString(2)
        // 补前导零
        if (s.length < width) "0" * (width - s.length) + s else s
    }

    def genPat(funct7: String, funct3: UInt, opcode: UInt): BitPat = {
        BitPat("b" + funct7 + "_?????_?????_" + UStr(funct3, 3) + "_?????_" + UStr(opcode, 7))
    }
    def genPatShiftImm64(funct6: String, funct3: UInt, opcode: UInt): BitPat = {
        BitPat("b" + funct6 + "_??????_?????_" + UStr(funct3, 3) + "_?????_" + UStr(opcode, 7))
    }
    // 对于没有 funct7 的情况
    def genPat(funct3: UInt, opcode: UInt): BitPat = {
        BitPat("b???????_?????_?????_" + UStr(funct3, 3) + "_?????_" + UStr(opcode, 7))
    }
    // 只有 opcode 的情况
    def genPat(opcode: UInt): BitPat = {
        BitPat("b???????_?????_?????_???_?????_" + UStr(opcode, 7))
    }

    def instructions: Array[InstrEntry]
}
