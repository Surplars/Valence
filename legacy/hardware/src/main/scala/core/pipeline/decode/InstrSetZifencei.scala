package soc.core.pipeline.decode

import soc.isa._

import chisel3._
import chisel3.util.BitPat
import soc.core.pipeline.{ALUOps, BranchType, CSROps, OpSel}

object InstrSetZifencei extends InstrProvider {
    def instructions: Array[InstrEntry] = Array(
        InstrEntry(
            BitPat("b???????_?????_?????_001_?????_0001111"),
            List(Y, OpSel.ZERO, OpSel.ZERO, ALUOps.NOP, N, N, N, CSROps.None, BranchType.None),
            Extension.Zifencei
        )
    )
}
