package soc.core.ooo

import chisel3._

/** Immutable scheduling class, deliberately independent of instruction legality.
  * This reproduces the existing head-drain predicates. The accepted allocation
  * edge stores one bit per ROB row; live/system/ready/recovery authority remains
  * at the original consumer. There is no new stage, port, owner or credit.
  */
object HeadDrainClass {
    def apply(original: UInt, expanded: UInt, p: OooParams): Bool = {
        val instruction = Mux(p.compressedInstructions.B && original(1, 0) =/= 3.U,
            expanded, original)
        val csr = instruction(31, 20)
        val pmp = if (p.pmpEntries > 0)
            instruction(6, 0) === "h73".U && instruction(14, 12) =/= 0.U &&
                (csr === "h3a0".U || csr === "h3a2".U ||
                (csr >= "h3b0".U && csr < (0x3b0 + p.pmpEntries).U))
        else false.B
        val returns = instruction === "h30200073".U || instruction === "h10200073".U
        val vm = if (p.virtualMemoryLevels > 0) {
            val sfence = instruction(31, 25) === "b0001001".U && instruction(14, 7) === 0.U &&
                instruction(6, 0) === "h73".U
            val satpWrite = instruction(6, 0) === "h73".U && instruction(14, 12) =/= 0.U &&
                csr === "h180".U &&
                (instruction(13, 12) === 1.U || instruction(19, 15) =/= 0.U)
            sfence || satpWrite
        } else false.B
        val fenceI = instruction(6, 0) === "h0f".U && instruction(14, 12) === 1.U
        pmp || returns || vm || fenceI
    }
}
