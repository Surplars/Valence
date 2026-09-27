package soc.isa

import chisel3._
import chisel3.util._

object Compressed {
    private def sext(value: UInt, bits: Int, xlen: Int = 32): UInt =
        Cat(Fill(xlen - bits, value(bits - 1)), value)
    private def low(value: UInt, bits: Int): UInt =
        if (value.getWidth <= bits) value.pad(bits) else value(bits - 1, 0)

    private def rvcReg(value: UInt): UInt = Cat("b01".U(2.W), value)
    private def i(opcode: UInt, rd: UInt, funct3: UInt, rs1: UInt, imm: UInt): UInt =
        Cat(low(imm, 12), low(rs1, 5), low(funct3, 3), low(rd, 5), low(opcode, 7))
    private def r(opcode: UInt, rd: UInt, funct3: UInt, rs1: UInt, rs2: UInt, funct7: UInt): UInt =
        Cat(low(funct7, 7), low(rs2, 5), low(rs1, 5), low(funct3, 3), low(rd, 5), low(opcode, 7))
    private def s(opcode: UInt, funct3: UInt, rs1: UInt, rs2: UInt, imm: UInt): UInt =
        Cat(imm(11, 5), low(rs2, 5), low(rs1, 5), low(funct3, 3), imm(4, 0), low(opcode, 7))
    private def b(opcode: UInt, funct3: UInt, rs1: UInt, rs2: UInt, imm: UInt): UInt =
        Cat(imm(12), imm(10, 5), low(rs2, 5), low(rs1, 5), low(funct3, 3), imm(4, 1), imm(11), low(opcode, 7))
    private def u(opcode: UInt, rd: UInt, imm: UInt): UInt =
        Cat(imm(31, 12), low(rd, 5), low(opcode, 7))
    private def j(opcode: UInt, rd: UInt, imm: UInt): UInt =
        Cat(imm(20), imm(10, 1), imm(11), imm(19, 12), low(rd, 5), low(opcode, 7))

    def expand(instr: UInt, rv64: Boolean = true): (UInt, Bool) = {
        val q = instr(1, 0)
        val funct3 = instr(15, 13)
        val rd = instr(11, 7)
        val rs1 = instr(11, 7)
        val rs2 = instr(6, 2)
        val rdPrime = rvcReg(instr(4, 2))
        val rs1Prime = rvcReg(instr(9, 7))
        val rs2Prime = rvcReg(instr(4, 2))
        val shamt = Cat(instr(12), instr(6, 2))

        val addiImm = sext(Cat(instr(12), instr(6, 2)), 6)
        val addi4spnImm = Cat(0.U(22.W), instr(10, 7), instr(12, 11), instr(5), instr(6), 0.U(2.W))
        val lwImm = Cat(0.U(25.W), instr(5), instr(12, 10), instr(6), 0.U(2.W))
        val ldImm = Cat(0.U(24.W), instr(6, 5), instr(12, 10), 0.U(3.W))
        val swImm = lwImm
        val sdImm = ldImm
        val lwspImm = Cat(0.U(24.W), instr(3, 2), instr(12), instr(6, 4), 0.U(2.W))
        val ldspImm = Cat(0.U(23.W), instr(4, 2), instr(12), instr(6, 5), 0.U(3.W))
        val swspImm = Cat(0.U(24.W), instr(8, 7), instr(12, 9), 0.U(2.W))
        val sdspImm = Cat(0.U(23.W), instr(9, 7), instr(12, 10), 0.U(3.W))
        val luiImm = sext(Cat(instr(12), instr(6, 2), 0.U(12.W)), 18)
        val addi16spImm = sext(Cat(instr(12), instr(4, 3), instr(5), instr(2), instr(6), 0.U(4.W)), 10)
        val jImm = sext(Cat(instr(12), instr(8), instr(10, 9), instr(6), instr(7), instr(2), instr(11), instr(5, 3), 0.U(1.W)), 12)
        val bImm = sext(Cat(instr(12), instr(6, 5), instr(2), instr(11, 10), instr(4, 3), 0.U(1.W)), 9)

        val addi = i(Opcode.OP_IMM, rd, Funct3.I.ADDI, rd, addiImm)
        val addiw = i(Opcode.OP_IMM_32, rd, Funct3.I.ADDIW, rd, addiImm)
        val li = i(Opcode.OP_IMM, rd, Funct3.I.ADDI, 0.U, addiImm)
        val addi16sp = i(Opcode.OP_IMM, 2.U, Funct3.I.ADDI, 2.U, addi16spImm)
        val lui = u(Opcode.LUI, rd, luiImm)
        val addi4spn = i(Opcode.OP_IMM, rdPrime, Funct3.I.ADDI, 2.U, addi4spnImm)
        val lw = i(Opcode.LOAD, rdPrime, Funct3.I.LW, rs1Prime, lwImm)
        val ld = i(Opcode.LOAD, rdPrime, Funct3.I.LD, rs1Prime, ldImm)
        val sw = s(Opcode.STORE, Funct3.I.SW, rs1Prime, rs2Prime, swImm)
        val sd = s(Opcode.STORE, Funct3.I.SD, rs1Prime, rs2Prime, sdImm)
        val lwsp = i(Opcode.LOAD, rd, Funct3.I.LW, 2.U, lwspImm)
        val ldsp = i(Opcode.LOAD, rd, Funct3.I.LD, 2.U, ldspImm)
        val swsp = s(Opcode.STORE, Funct3.I.SW, 2.U, rs2, swspImm)
        val sdsp = s(Opcode.STORE, Funct3.I.SD, 2.U, rs2, sdspImm)
        val jal = j(Opcode.JAL, 0.U, jImm)
        val beqz = b(Opcode.BRANCH, Funct3.I.BEQ, rs1Prime, 0.U, bImm)
        val bnez = b(Opcode.BRANCH, Funct3.I.BNE, rs1Prime, 0.U, bImm)
        val slli = i(Opcode.OP_IMM, rd, Funct3.I.SLLI, rd, shamt)
        val srli = i(Opcode.OP_IMM, rs1Prime, Funct3.I.SRLI_SRAI, rs1Prime, shamt)
        val srai = i(Opcode.OP_IMM, rs1Prime, Funct3.I.SRLI_SRAI, rs1Prime, Cat("b010000".U(6.W), shamt)(11, 0))
        val andi = i(Opcode.OP_IMM, rs1Prime, Funct3.I.ANDI, rs1Prime, addiImm)
        val sub = r(Opcode.OP, rs1Prime, Funct3.I.ADDSUB, rs1Prime, rs2Prime, "b0100000".U)
        val xor = r(Opcode.OP, rs1Prime, Funct3.I.XOR, rs1Prime, rs2Prime, "b0000000".U)
        val or = r(Opcode.OP, rs1Prime, Funct3.I.OR, rs1Prime, rs2Prime, "b0000000".U)
        val and = r(Opcode.OP, rs1Prime, Funct3.I.AND, rs1Prime, rs2Prime, "b0000000".U)
        val subw = r(Opcode.OP_32, rs1Prime, Funct3.I.ADDW, rs1Prime, rs2Prime, "b0100000".U)
        val addw = r(Opcode.OP_32, rs1Prime, Funct3.I.ADDW, rs1Prime, rs2Prime, "b0000000".U)
        val jr = i(Opcode.JALR, 0.U, 0.U, rs1, 0.U)
        val jalr = i(Opcode.JALR, 1.U, 0.U, rs1, 0.U)
        val mv = r(Opcode.OP, rd, Funct3.I.ADDSUB, 0.U, rs2, "b0000000".U)
        val add = r(Opcode.OP, rd, Funct3.I.ADDSUB, rd, rs2, "b0000000".U)
        val ebreak = "h00100073".U(32.W)
        val illegal = 0.U(32.W)

        val expanded = WireDefault(illegal)
        val legal = WireDefault(false.B)

        switch(q) {
            is("b00".U) {
                switch(funct3) {
                    is("b000".U) { expanded := addi4spn; legal := instr(12, 5) =/= 0.U }
                    is("b010".U) { expanded := lw; legal := true.B }
                    is("b011".U) { expanded := ld; legal := rv64.B }
                    is("b110".U) { expanded := sw; legal := true.B }
                    is("b111".U) { expanded := sd; legal := rv64.B }
                }
            }
            is("b01".U) {
                switch(funct3) {
                    is("b000".U) { expanded := addi; legal := true.B }
                    is("b001".U) { expanded := addiw; legal := rv64.B && rd =/= 0.U }
                    is("b010".U) { expanded := li; legal := true.B } // rd=x0 is a HINT.
                    is("b011".U) {
                        expanded := Mux(rd === 2.U, addi16sp, lui)
                        legal := Mux(rd === 2.U, addi16spImm =/= 0.U, luiImm =/= 0.U)
                    }
                    is("b101".U) { expanded := jal; legal := true.B }
                    is("b110".U) { expanded := beqz; legal := true.B }
                    is("b111".U) { expanded := bnez; legal := true.B }
                    is("b100".U) {
                        switch(instr(11, 10)) {
                            is("b00".U) { expanded := srli; legal := true.B }
                            is("b01".U) { expanded := srai; legal := true.B }
                            is("b10".U) { expanded := andi; legal := true.B }
                            is("b11".U) {
                                switch(Cat(instr(12), instr(6, 5))) {
                                    is("b000".U) { expanded := sub; legal := true.B }
                                    is("b001".U) { expanded := xor; legal := true.B }
                                    is("b010".U) { expanded := or; legal := true.B }
                                    is("b011".U) { expanded := and; legal := true.B }
                                    is("b100".U) { expanded := subw; legal := rv64.B }
                                    is("b101".U) { expanded := addw; legal := rv64.B }
                                }
                            }
                        }
                    }
                }
            }
            is("b10".U) {
                switch(funct3) {
                    is("b000".U) { expanded := slli; legal := true.B }
                    is("b010".U) { expanded := lwsp; legal := rd =/= 0.U }
                    is("b011".U) { expanded := ldsp; legal := rv64.B && rd =/= 0.U }
                    is("b100".U) {
                        when(instr(12) === 0.U && rs2 === 0.U) {
                            expanded := jr
                            legal := rs1 =/= 0.U
                        }.elsewhen(instr(12) === 1.U && rs2 === 0.U) {
                            expanded := Mux(rs1 === 0.U, ebreak, jalr)
                            legal := true.B
                        }.elsewhen(instr(12) === 0.U && rs2 =/= 0.U) {
                            expanded := mv
                            legal := true.B
                        }.elsewhen(instr(12) === 1.U && rs2 =/= 0.U) {
                            expanded := add
                            legal := true.B
                        }
                    }
                    is("b110".U) { expanded := swsp; legal := true.B }
                    is("b111".U) { expanded := sdsp; legal := rv64.B }
                }
            }
        }

        (expanded, legal)
    }
}
