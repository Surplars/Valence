package soc.core.ooo

import chisel3._
import chisel3.util._

/** RV64 H 1.0 encodings. Permission is evaluated only at the irrevocable ROB head. */
object HypervisorInstruction {
    def load(inst: UInt): Bool = {
        val variant = inst(24, 20)
        val valid = MuxLookup(inst(27, 26), false.B)(Seq(
            0.U -> (variant === 0.U || variant === 1.U),
            1.U -> (variant === 0.U || variant === 1.U || variant === 3.U),
            2.U -> (variant === 0.U || variant === 1.U || variant === 3.U),
            3.U -> (variant === 0.U)))
        inst(6, 0) === 0x73.U && inst(14, 12) === 4.U && inst(31, 28) === 6.U && !inst(25) && valid
    }
    def store(inst: UInt): Bool = inst(6, 0) === 0x73.U && inst(14, 12) === 4.U &&
        inst(31, 28) === 6.U && inst(25) && inst(11, 7) === 0.U
    def memory(inst: UInt): Bool = load(inst) || store(inst)
    def fenceVs(inst: UInt): Bool = inst(6, 0) === 0x73.U && inst(14, 7) === 0.U && inst(31, 25) === 0x11.U
    def fenceGuest(inst: UInt): Bool = inst(6, 0) === 0x73.U && inst(14, 7) === 0.U && inst(31, 25) === 0x31.U
    def fence(inst: UInt): Bool = fenceVs(inst) || fenceGuest(inst)
    def recognized(inst: UInt): Bool = memory(inst) || fence(inst)
}
