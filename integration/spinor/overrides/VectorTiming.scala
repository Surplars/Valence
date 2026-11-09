package vpu

import chisel3._
import chisel3.util._

/** Same-edge full-width equality using bounded XOR groups, without a carry comparator. */
object VectorTiming {
    /** VSET source normalization at command capture; no architectural state is written here. */
    def vsetOperands(instruction: UInt, scalarType: UInt, sourceAvl: UInt, currentVl: UInt): (UInt, UInt) = {
        val registerType = instruction(31, 25) === 0x40.U
        val immediateAvl = instruction(31, 30) === 3.U
        val rs1 = instruction(19, 15)
        val rd = instruction(11, 7)
        val selectedType = Mux(registerType, scalarType,
            Mux(immediateAvl, instruction(29, 20), instruction(30, 20)).pad(64))
        val selectedAvl = Mux(immediateAvl, rs1.pad(64),
            Mux(rs1 === 0.U, Mux(rd === 0.U, currentVl.pad(64), "hffffffffffffffff".U), sourceAvl))
        (selectedType, selectedAvl)
    }

    def equal(left: UInt, right: UInt): Bool = {
        val width = math.max(left.getWidth, right.getWidth)
        val a = left.pad(width)
        val b = right.pad(width)
        VecInit((0 until width by 6).map { low =>
            val high = math.min(width - 1, low + 5)
            !(a(high, low) ^ b(high, low)).orR
        }).asUInt.andR
    }
}
