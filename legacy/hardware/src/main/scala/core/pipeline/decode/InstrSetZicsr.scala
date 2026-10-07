package soc.core.pipeline.decode

import soc.isa._

import chisel3._

import soc.core.pipeline.ALUOps
import soc.core.pipeline.OpSel
import soc.core.pipeline.BranchType
import soc.core.pipeline.CSROps
import chisel3.util.BitPat

object InstrSetZicsr extends InstrProvider {
    def instructions: Array[InstrEntry] = Array(
        // CSRRW
        InstrEntry(
            genPat(0b001.U, Opcode.SYSTEM),
            CSR(CSROps.RW),
            Extension.Zicsr
        ),
        // CSRRS
        InstrEntry(
            genPat(0b010.U, Opcode.SYSTEM),
            CSR(CSROps.RS),
            Extension.Zicsr
        ),
        // CSRRC
        InstrEntry(
            genPat(0b011.U, Opcode.SYSTEM),
            CSR(CSROps.RC),
            Extension.Zicsr
        ),
        // CSRRWI
        InstrEntry(
            genPat(0b101.U, Opcode.SYSTEM),
            CSR(CSROps.RWI),
            Extension.Zicsr
        ),
        // CSRRSI
        InstrEntry(
            genPat(0b110.U, Opcode.SYSTEM),
            CSR(CSROps.RSI),
            Extension.Zicsr
        ),
        // CSRRCI
        InstrEntry(
            genPat(0b111.U, Opcode.SYSTEM),
            CSR(CSROps.RCI),
            Extension.Zicsr
        ),
        // SRET
        InstrEntry(
            BitPat("b0001000_00010_00000_000_00000_1110011"),
            List(Y, OpSel.ZERO, OpSel.ZERO, ALUOps.NOP, N, N, N, CSROps.None, BranchType.SRET),
            Extension.Zicsr
        ),
        // MRET
        InstrEntry(
            BitPat("b0011000_00010_00000_000_00000_1110011"),
            List(Y, OpSel.ZERO, OpSel.ZERO, ALUOps.NOP, N, N, N, CSROps.None, BranchType.MRET),
            Extension.Zicsr
        ),
        // MNRET
        InstrEntry(
            BitPat("b0111000_00010_00000_000_00000_1110011"),
            List(Y, OpSel.ZERO, OpSel.ZERO, ALUOps.NOP, N, N, N, CSROps.None, BranchType.MNRET),
            Extension.Zicsr
        ),
        // WFI
        InstrEntry(
            BitPat("b0001000_00101_00000_000_00000_1110011"),
            List(Y, OpSel.ZERO, OpSel.ZERO, ALUOps.NOP, N, N, N, CSROps.None, BranchType.WFI),
            Extension.Zicsr
        )
    )
}
