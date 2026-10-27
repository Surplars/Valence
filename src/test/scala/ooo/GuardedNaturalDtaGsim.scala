package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util.experimental.BoringUtils

/** Same real DTA/DTLB fixture with one passive captured-hint observation. */
class GuardedNaturalDtaGsim(guarded: Boolean) extends RegisteredRawCertifiedFlowGsim(false,
    Some("full-r1-m3-checked-flow-store-row-elastic-proof" + (if (guarded) "-guarded-natural-pmp" else ""))) {
    override def desiredName: String = "RegisteredRawCertifiedFlowGsim"
    val checkedHint = IO(Output(Bool()))
    checkedHint := BoringUtils.bore(adapter.checked.get.enq.bits.request.prefetchNextAllowed)
    require(p.guardedNaturalDataPmp == guarded)
}
object GuardedNaturalDtaGsimMain extends App {
    require(args.length == 2 && Set("control", "guarded").contains(args(1)))
    ChiselStage.emitCHIRRTLFile(new GuardedNaturalDtaGsim(args(1) == "guarded"),
        Array("--target-dir", args.head))
}
