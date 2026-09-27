package soc.core.pipeline.decode

import soc.isa._

import chisel3._
import chisel3.util.BitPat
import soc.core.pipeline.{ALUOps, BranchType, CSROps, OpSel}

object InstrSetS extends InstrProvider {
    def instructions: Array[InstrEntry] = Array(
        InstrEntry(
            BitPat("b0001001_?????_?????_000_00000_1110011"),
            List(Y, OpSel.ZERO, OpSel.ZERO, ALUOps.NOP, N, N, N, CSROps.None, BranchType.None),
            Extension.S
        )
    )
}
