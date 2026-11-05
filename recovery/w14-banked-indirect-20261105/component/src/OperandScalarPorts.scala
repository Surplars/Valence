package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._
import scala.collection.immutable.ListMap

/** Scalar top-level fields avoid the pinned GSIM generator's invalid Vec input
  * setters. The actual DUT still uses its original Vec operand interfaces.
  */
class OperandScalarPorts(width: Int, count: Int) extends Record {
    override val elements: ListMap[String, Data] = ListMap((0 until count).map(i =>
        s"r$i" -> UInt(width.W)): _*)
    def at(i: Int): UInt = elements(s"r$i").asInstanceOf[UInt]
}

