package soc.core.pipeline.decode

import soc.isa._

import chisel3._
import chisel3.util._

import soc.core.pipeline.ALUOps
import soc.core.pipeline.OpSel
import soc.core.pipeline.BranchType
import soc.core.pipeline.CSROps

case class InstrEntry(
    pattern: BitPat,
    ctrl: List[Data],
    ext: Extension.Value = Extension.RV64I // 默认为基础指令集
)

object InstrTable {
    val defaultCtrl =
        List(false.B, OpSel.ZERO, OpSel.ZERO, ALUOps.NOP, false.B, false.B, false.B, CSROps.None, BranchType.None)

    private val allProviders =
        Seq(InstrSetZicsr, InstrSetZifencei, InstrSetS, InstrSetI, InstrSetM, InstrSetA, InstrSetB)

    private def isFeatureSupported(f: Extension.Value, enabled: Set[Extension.Value]): Boolean = f match {
        case Extension.RV32I    => enabled.contains(Extension.RV64I) || enabled.contains(Extension.RV32I)
        case Extension.RV32M    => enabled.contains(Extension.RV64M) || enabled.contains(Extension.RV32M)
        case Extension.RV32A    => enabled.contains(Extension.RV64A) || enabled.contains(Extension.RV32A)
        case Extension.RV64I    => enabled.contains(Extension.RV64I)
        case Extension.RV64M    => enabled.contains(Extension.RV64M)
        case Extension.RV64A    => enabled.contains(Extension.RV64A)
        case Extension.Zicsr    => enabled.contains(Extension.Zicsr)
        case Extension.Zifencei => enabled.contains(Extension.Zifencei)
        case other              => enabled.contains(other)
    }

    def getTable(enabledExt: Set[Extension.Value]): Array[(BitPat, List[Data])] = {
        val instructions = allProviders.flatMap(_.instructions)
        instructions
            .filter { entry => isFeatureSupported(entry.ext, enabledExt) }
            .map { entry => (entry.pattern -> entry.ctrl) }
            .toArray
    }

}
