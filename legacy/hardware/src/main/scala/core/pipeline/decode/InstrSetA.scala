package soc.core.pipeline.decode

import soc.isa._

import chisel3._
import chisel3.util.BitPat

object InstrSetA extends InstrProvider {
    private def amoPat(funct5: String, funct3: UInt, rs2: String = "?????"): BitPat = {
        BitPat("b" + funct5 + "_??_" + rs2 + "_?????_" + UStr(funct3, 3) + "_?????_0101111")
    }

    def instructions: Array[InstrEntry] = Array(
        InstrEntry(amoPat(Funct5.A.LR, Funct3.A.W, "00000"), ATOMIC, Extension.RV32A),
        InstrEntry(amoPat(Funct5.A.SC, Funct3.A.W), ATOMIC, Extension.RV32A),
        InstrEntry(amoPat(Funct5.A.SWAP, Funct3.A.W), ATOMIC, Extension.RV32A),
        InstrEntry(amoPat(Funct5.A.ADD, Funct3.A.W), ATOMIC, Extension.RV32A),
        InstrEntry(amoPat(Funct5.A.XOR, Funct3.A.W), ATOMIC, Extension.RV32A),
        InstrEntry(amoPat(Funct5.A.AND, Funct3.A.W), ATOMIC, Extension.RV32A),
        InstrEntry(amoPat(Funct5.A.OR, Funct3.A.W), ATOMIC, Extension.RV32A),
        InstrEntry(amoPat(Funct5.A.MIN, Funct3.A.W), ATOMIC, Extension.RV32A),
        InstrEntry(amoPat(Funct5.A.MAX, Funct3.A.W), ATOMIC, Extension.RV32A),
        InstrEntry(amoPat(Funct5.A.MINU, Funct3.A.W), ATOMIC, Extension.RV32A),
        InstrEntry(amoPat(Funct5.A.MAXU, Funct3.A.W), ATOMIC, Extension.RV32A),
        InstrEntry(amoPat(Funct5.A.LR, Funct3.A.D, "00000"), ATOMIC, Extension.RV64A),
        InstrEntry(amoPat(Funct5.A.SC, Funct3.A.D), ATOMIC, Extension.RV64A),
        InstrEntry(amoPat(Funct5.A.SWAP, Funct3.A.D), ATOMIC, Extension.RV64A),
        InstrEntry(amoPat(Funct5.A.ADD, Funct3.A.D), ATOMIC, Extension.RV64A),
        InstrEntry(amoPat(Funct5.A.XOR, Funct3.A.D), ATOMIC, Extension.RV64A),
        InstrEntry(amoPat(Funct5.A.AND, Funct3.A.D), ATOMIC, Extension.RV64A),
        InstrEntry(amoPat(Funct5.A.OR, Funct3.A.D), ATOMIC, Extension.RV64A),
        InstrEntry(amoPat(Funct5.A.MIN, Funct3.A.D), ATOMIC, Extension.RV64A),
        InstrEntry(amoPat(Funct5.A.MAX, Funct3.A.D), ATOMIC, Extension.RV64A),
        InstrEntry(amoPat(Funct5.A.MINU, Funct3.A.D), ATOMIC, Extension.RV64A),
        InstrEntry(amoPat(Funct5.A.MAXU, Funct3.A.D), ATOMIC, Extension.RV64A)
    )
}
