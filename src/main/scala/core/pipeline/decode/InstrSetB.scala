package soc.core.pipeline.decode

import soc.isa._

import chisel3._
import chisel3.util.BitPat

import soc.core.pipeline.ALUOps
import soc.core.pipeline.OpSel

object InstrSetB extends InstrProvider {
    private def r(funct7: String, funct3: String): BitPat =
        BitPat("b" + funct7 + "_?????_?????_" + funct3 + "_?????_0110011")

    private def rw(funct7: String, funct3: String): BitPat =
        BitPat("b" + funct7 + "_?????_?????_" + funct3 + "_?????_0111011")

    private def shi(funct6: String, funct3: String): BitPat =
        BitPat("b" + funct6 + "_??????_?????_" + funct3 + "_?????_0010011")

    private def shiw(funct7: String, funct3: String): BitPat =
        BitPat("b" + funct7 + "_?????_?????_" + funct3 + "_?????_0011011")

    def instructions: Array[InstrEntry] = Array(
        InstrEntry(r("0100000", "111"), ALU(ALUOps.ANDN, OpSel.RS1, OpSel.RS2), Extension.Zbb),
        InstrEntry(r("0100000", "110"), ALU(ALUOps.ORN, OpSel.RS1, OpSel.RS2), Extension.Zbb),
        InstrEntry(r("0100000", "100"), ALU(ALUOps.XNOR, OpSel.RS1, OpSel.RS2), Extension.Zbb),
        InstrEntry(r("0110000", "001"), ALU(ALUOps.ROL, OpSel.RS1, OpSel.RS2), Extension.Zbb),
        InstrEntry(r("0110000", "101"), ALU(ALUOps.ROR, OpSel.RS1, OpSel.RS2), Extension.Zbb),
        InstrEntry(rw("0110000", "001"), ALU(ALUOps.ROLW, OpSel.RS1, OpSel.RS2), Extension.Zbb),
        InstrEntry(rw("0110000", "101"), ALU(ALUOps.RORW, OpSel.RS1, OpSel.RS2), Extension.Zbb),
        InstrEntry(r("0000101", "100"), ALU(ALUOps.MIN, OpSel.RS1, OpSel.RS2), Extension.Zbb),
        InstrEntry(r("0000101", "101"), ALU(ALUOps.MINU, OpSel.RS1, OpSel.RS2), Extension.Zbb),
        InstrEntry(r("0000101", "110"), ALU(ALUOps.MAX, OpSel.RS1, OpSel.RS2), Extension.Zbb),
        InstrEntry(r("0000101", "111"), ALU(ALUOps.MAXU, OpSel.RS1, OpSel.RS2), Extension.Zbb),
        InstrEntry(
            BitPat("b011000000000_?????_001_?????_0010011"),
            ALU(ALUOps.CLZ, OpSel.RS1, OpSel.ZERO),
            Extension.Zbb
        ),
        InstrEntry(
            BitPat("b011000000001_?????_001_?????_0010011"),
            ALU(ALUOps.CTZ, OpSel.RS1, OpSel.ZERO),
            Extension.Zbb
        ),
        InstrEntry(
            BitPat("b011000000010_?????_001_?????_0010011"),
            ALU(ALUOps.CPOP, OpSel.RS1, OpSel.ZERO),
            Extension.Zbb
        ),
        InstrEntry(
            BitPat("b0110000_00000_?????_001_?????_0011011"),
            ALU(ALUOps.CLZW, OpSel.RS1, OpSel.ZERO),
            Extension.Zbb
        ),
        InstrEntry(
            BitPat("b0110000_00001_?????_001_?????_0011011"),
            ALU(ALUOps.CTZW, OpSel.RS1, OpSel.ZERO),
            Extension.Zbb
        ),
        InstrEntry(
            BitPat("b0110000_00010_?????_001_?????_0011011"),
            ALU(ALUOps.CPOPW, OpSel.RS1, OpSel.ZERO),
            Extension.Zbb
        ),
        InstrEntry(
            BitPat("b011000000100_?????_001_?????_0010011"),
            ALU(ALUOps.SEXTB, OpSel.RS1, OpSel.ZERO),
            Extension.Zbb
        ),
        InstrEntry(
            BitPat("b011000000101_?????_001_?????_0010011"),
            ALU(ALUOps.SEXTH, OpSel.RS1, OpSel.ZERO),
            Extension.Zbb
        ),
        InstrEntry(
            BitPat("b0000100_00000_?????_100_?????_0111011"),
            ALU(ALUOps.ZEXTH, OpSel.RS1, OpSel.ZERO),
            Extension.Zbb
        ),
        InstrEntry(shi("011000", "101"), ALU(ALUOps.RORI, OpSel.RS1, OpSel.IMM), Extension.Zbb),
        InstrEntry(shiw("0110000", "101"), ALU(ALUOps.RORIW, OpSel.RS1, OpSel.IMM), Extension.Zbb),
        InstrEntry(
            BitPat("b001010000111_?????_101_?????_0010011"),
            ALU(ALUOps.ORCB, OpSel.RS1, OpSel.ZERO),
            Extension.Zbb
        ),
        InstrEntry(
            BitPat("b011010111000_?????_101_?????_0010011"),
            ALU(ALUOps.REV8, OpSel.RS1, OpSel.ZERO),
            Extension.Zbb
        ),
        InstrEntry(rw("0000100", "000"), ALU(ALUOps.ADDUW, OpSel.RS1, OpSel.RS2), Extension.Zba),
        InstrEntry(
            BitPat("b000010_??????_?????_001_?????_0011011"),
            ALU(ALUOps.SLLIUW, OpSel.RS1, OpSel.IMM),
            Extension.Zba
        ),
        InstrEntry(r("0010000", "010"), ALU(ALUOps.SH1ADD, OpSel.RS1, OpSel.RS2), Extension.Zba),
        InstrEntry(r("0010000", "100"), ALU(ALUOps.SH2ADD, OpSel.RS1, OpSel.RS2), Extension.Zba),
        InstrEntry(r("0010000", "110"), ALU(ALUOps.SH3ADD, OpSel.RS1, OpSel.RS2), Extension.Zba),
        InstrEntry(rw("0010000", "010"), ALU(ALUOps.SH1ADDUW, OpSel.RS1, OpSel.RS2), Extension.Zba),
        InstrEntry(rw("0010000", "100"), ALU(ALUOps.SH2ADDUW, OpSel.RS1, OpSel.RS2), Extension.Zba),
        InstrEntry(rw("0010000", "110"), ALU(ALUOps.SH3ADDUW, OpSel.RS1, OpSel.RS2), Extension.Zba),
        InstrEntry(r("0100100", "001"), ALU(ALUOps.BCLR, OpSel.RS1, OpSel.RS2), Extension.Zbs),
        InstrEntry(r("0100100", "101"), ALU(ALUOps.BEXT, OpSel.RS1, OpSel.RS2), Extension.Zbs),
        InstrEntry(r("0110100", "001"), ALU(ALUOps.BINV, OpSel.RS1, OpSel.RS2), Extension.Zbs),
        InstrEntry(r("0010100", "001"), ALU(ALUOps.BSET, OpSel.RS1, OpSel.RS2), Extension.Zbs),
        InstrEntry(shi("010010", "001"), ALU(ALUOps.BCLR, OpSel.RS1, OpSel.IMM), Extension.Zbs),
        InstrEntry(shi("010010", "101"), ALU(ALUOps.BEXT, OpSel.RS1, OpSel.IMM), Extension.Zbs),
        InstrEntry(shi("011010", "001"), ALU(ALUOps.BINV, OpSel.RS1, OpSel.IMM), Extension.Zbs),
        InstrEntry(shi("001010", "001"), ALU(ALUOps.BSET, OpSel.RS1, OpSel.IMM), Extension.Zbs)
    )
}
