package soc.core.inorder

import chisel3._
import chisel3.util._

/** Numerical ownership only, not a ROB token. Constant in the CPU; full-width in independent producer tests. */
class I1FloatingPointToken extends Bundle {
    val index = UInt(4.W)
    val tag = UInt(64.W)
}
class I1FloatingPointCommand(p: FiveStageConfig) extends Bundle {
    val token = new I1FloatingPointToken
    val instruction = UInt(32.W)
    val integerSource = UInt(64.W)
}
class I1FloatingPointExecution(p: FiveStageConfig) extends Bundle {
    val command = new I1FloatingPointCommand(p)
    val operands = Vec(3, UInt(64.W))
    val rounding = UInt(3.W)
}
class I1FloatingPointResult(p: FiveStageConfig) extends Bundle {
    val token = new I1FloatingPointToken
    val value = UInt(64.W)
    val flags = UInt(5.W)
    val exception = Bool()
    val cause = UInt(6.W)
    val tval = UInt(64.W)
}
class I1FloatingPointCommit extends Bundle {
    val write = Bool()
    val data = UInt(64.W)
    val flags = UInt(5.W)
}
object I1FloatingPointBits {
    def boxSingle(value: UInt): UInt = Cat("hffffffff".U(32.W), value(31, 0))
    def operand(value: UInt, checkSingleBox: Bool): UInt =
        Mux(checkSingleBox && !value(63, 32).andR, "hffffffff7fc00000".U(64.W), value)
}
