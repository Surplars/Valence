package soc.core.ooo

import chisel3._
import chisel3.util._

/** RV64 F 2.2 / D 2.2 encoding and architectural metadata, ISA 20250508.
  * Reserved rounding modes are checked after resolving frm in FloatingPointState.
  * No FP register number is exposed as an integer PRF dependency.
  */
object FloatingPointDecode {
    private def op(inst: UInt, function: Int): Bool = inst(6, 0) === "h53".U &&
        inst(31, 26) === (function >> 1).U
    def add(inst: UInt): Bool = op(inst, 0x00) || op(inst, 0x04)
    def multiply(inst: UInt): Bool = op(inst, 0x08)
    def divide(inst: UInt): Bool = op(inst, 0x0c)
    def sqrt(inst: UInt): Bool = op(inst, 0x2c) && inst(24, 20) === 0.U
    def fused(inst: UInt): Bool = Seq(0x43, 0x47, 0x4b, 0x4f).map(n => inst(6, 0) === n.U).reduce(_ || _)
    def sign(inst: UInt): Bool = op(inst, 0x10) && inst(14, 12) <= 2.U
    def minMax(inst: UInt): Bool = op(inst, 0x14) && inst(14, 12) <= 1.U
    def compare(inst: UInt): Bool = op(inst, 0x50) && inst(14, 12) <= 2.U
    def toInteger(inst: UInt): Bool = op(inst, 0x60) && inst(24, 20) <= 3.U
    def fromInteger(inst: UInt): Bool = op(inst, 0x68) && inst(24, 20) <= 3.U
    def convert(inst: UInt): Bool = inst(6, 0) === "h53".U &&
        ((inst(31, 25) === 0x20.U && inst(24, 20) === 1.U) ||
         (inst(31, 25) === 0x21.U && inst(24, 20) === 0.U))
    def moveToInteger(inst: UInt): Bool = op(inst, 0x70) && inst(24, 20) === 0.U && inst(14, 12) === 0.U
    def moveToFloat(inst: UInt): Bool = op(inst, 0x78) && inst(24, 20) === 0.U && inst(14, 12) === 0.U
    def classify(inst: UInt): Bool = op(inst, 0x70) && inst(24, 20) === 0.U && inst(14, 12) === 1.U
    def load(inst: UInt): Bool = inst(6, 0) === 0x07.U && (inst(14, 12) === 2.U || inst(14, 12) === 3.U)
    def store(inst: UInt): Bool = inst(6, 0) === 0x27.U && (inst(14, 12) === 2.U || inst(14, 12) === 3.U)
    def memory(inst: UInt): Bool = load(inst) || store(inst)
    def single(inst: UInt): Bool = Mux(memory(inst), inst(14, 12) === 2.U, !inst(25))
    def writesInteger(inst: UInt): Bool = toInteger(inst) || compare(inst) || classify(inst) || moveToInteger(inst)
    def readsInteger(inst: UInt): Bool = fromInteger(inst) || moveToFloat(inst) || memory(inst)
    def writesFp(inst: UInt): Bool = !writesInteger(inst) && !store(inst)
    def usesRounding(inst: UInt): Bool = add(inst) || multiply(inst) || divide(inst) || sqrt(inst) ||
        fused(inst) || toInteger(inst) || fromInteger(inst) || convert(inst)
    def writesFlags(inst: UInt): Bool = usesRounding(inst) || convert(inst) || compare(inst) || minMax(inst)
    def checkSingle(inst: UInt): Bool = !memory(inst) && !moveToInteger(inst) && !moveToFloat(inst) &&
        !fromInteger(inst) && Mux(convert(inst), inst(24, 20) === 0.U, single(inst))
    def supported(inst: UInt, c: FloatingPointConfig = FloatingPointConfig.fullFD): Bool = {
        val format = Mux(memory(inst), single(inst) || c.d.B,
            inst(26) === 0.U && (!inst(25) || c.d.B))
        c.f.B && format && (
            (c.addSubtract.B && add(inst)) || (c.multiply.B && multiply(inst)) ||
            (c.divide.B && divide(inst)) || (c.squareRoot.B && sqrt(inst)) ||
            (c.fusedMultiplyAdd.B && fused(inst)) ||
            (c.compareMinMax.B && (compare(inst) || minMax(inst))) ||
            (c.signClassMove.B && (sign(inst) || classify(inst) || moveToFloat(inst) || moveToInteger(inst))) ||
            (c.conversions.B && (toInteger(inst) || fromInteger(inst) || (c.d.B && convert(inst)))) ||
            (c.memory.B && memory(inst)))
    }
}

/** Compatibility names for existing head-ownership and test adapters. */
object FloatingPointSubset {
    def arithmetic(inst: UInt): Bool = FloatingPointDecode.add(inst)
    def moveToFloat(inst: UInt): Bool = FloatingPointDecode.moveToFloat(inst)
    def moveToInteger(inst: UInt): Bool = FloatingPointDecode.moveToInteger(inst)
    def load(inst: UInt): Bool = FloatingPointDecode.load(inst)
    def store(inst: UInt): Bool = FloatingPointDecode.store(inst)
    def memory(inst: UInt): Bool = FloatingPointDecode.memory(inst)
    def supported(inst: UInt): Bool = FloatingPointDecode.supported(inst)
}
