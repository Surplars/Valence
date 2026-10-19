package soc.core.inorder

import chisel3._
import chisel3.util._

/** Format metadata only, never an execute/permission proof.
  * Low4: standard32; high4: compressed16. Unsupported long prefixes set neither.
  */
object I1InstructionPredecode {
    def classify(data: UInt): UInt = {
        require(data.getWidth == 64)
        val standard = VecInit((0 until 4).map(i =>
            data(i * 16 + 1, i * 16).andR && !data(i * 16 + 4, i * 16 + 2).andR))
        val compressed = VecInit((0 until 4).map(i => !data(i * 16 + 1, i * 16).andR))
        Cat(compressed.asUInt, standard.asUInt)
    }
}
