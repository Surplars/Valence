package soc.core.ooo

import chisel3._
import chisel3.util._

/** Complete issue-boundary payload, not an accepted owner or another queue.
  * The optional prepared-store source never participates in the normal load
  * query/PMP input selection. All owner-sensitive sidebands join here instead.
  */
class PreparedStoreIssue(p: OooParams) extends Bundle {
    val operation = new MemoryOperation(p)
    val parallel = Bool()
    val destination = Valid(UInt(p.physBits.W))
}
