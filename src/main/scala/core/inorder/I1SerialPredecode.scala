package soc.core.inorder

import chisel3._
import chisel3.util._

/** Serial CLASS, including illegal encodings that the full decoder drains.
  * No permission/legality prediction. Captured at the existing IF/ID edge.
  */
object I1SerialPredecode {
    def apply(instruction: UInt, compressed: Bool, p: FiveStageConfig): Bool = {
        val opcode = instruction(6, 0)
        val native = opcode === "h0f".U || opcode === "h73".U ||
            (p.withA.B && opcode === "h2f".U) ||
            (p.withF.B && Seq(0x07, 0x27, 0x53, 0x43, 0x47, 0x4b, 0x4f)
                .map(n => opcode === n.U).reduce(_ || _))
        val quadrant = instruction(1, 0)
        val function = instruction(15, 13)
        // Reserved C.JR x0 expands to EBREAK too, but remains illegal.
        // Preserve its serial class even when bit12 is zero.
        val breakpointClass = quadrant === 2.U && function === 4.U &&
            instruction(11, 2) === 0.U
        val floatingClass = p.withF.B && (
            (quadrant === 0.U && (function === 1.U || function === 5.U)) ||
            (p.withD.B && quadrant === 2.U && (function === 1.U || function === 5.U)) ||
            ((p.xlen == 32).B && (quadrant === 0.U || quadrant === 2.U) &&
                (function === 3.U || function === 7.U)))
        Mux(p.withC.B && compressed, breakpointClass || floatingClass, native)
    }
}
