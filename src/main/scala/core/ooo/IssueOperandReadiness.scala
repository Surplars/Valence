package soc.core.ooo

import chisel3._
import chisel3.util._

/** Registered base readiness plus the unchanged same-cycle issue promises.
  * Promises authorize operand capture only; they are not PRF writes or completion
  * acceptance. Caller retains owner, pending, kill and exception authorization.
  */
object IssueOperandReadiness {
    def apply(source: UInt, registeredReady: Bool, load: ValidIO[UInt], alu: Seq[ValidIO[UInt]]): Bool =
        registeredReady || (load.valid && load.bits === source) ||
            alu.map(wake => wake.valid && wake.bits === source).reduce(_ || _)
}
