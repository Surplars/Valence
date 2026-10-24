package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._
import soc.platform.CommonA1RebuildProfile

/** Pure join contract only. Permission booleans are explicit already-checked
  * premises; real response/slot ownership is tested separately in ParallelLSU.
  */
class M3CanonicalForwardPredicateGsim extends Module {
    val p = CommonA1RebuildProfile.FullR1M3.config.coreParams
    val dut = Module(new CompletedCanonicalStoreForwarding(p))
    val io = IO(dut.io.cloneType)
    io <> dut.io
}
object M3CanonicalForwardPredicateGsimMain extends App {
    require(args.length == 1, "output-directory")
    ChiselStage.emitCHIRRTLFile(new M3CanonicalForwardPredicateGsim, Array("--target-dir", args.head))
}
