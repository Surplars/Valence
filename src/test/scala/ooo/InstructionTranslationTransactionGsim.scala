package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

/** Cycle peer only: the frozen implementation does not replace the independent
  * byte-range PMP and accepted-owner C++ oracle. The existing flat fixture and
  * generated top name deliberately let us reuse its unchanged host drivers.
  */
class InstructionTranslationTransactionGsim(words: Int, aligned: Boolean, stream: Boolean, turnover: Boolean)
    extends InstructionPermissionGsim(words, retimed = true, aligned = aligned,
        turnover = stream && turnover, identity = stream,
        exactParams = if (words == 2 && aligned && stream) Some(FpgaNextConfig.Selected.coreParams) else None) {
    override def desiredName: String = "InstructionPermissionGsim"
    val reference = Module(new FrozenInstructionTranslationAdapterBeforeTransactionBoundary(p))
    reference.io.virtual.request.valid := adapter.io.virtual.request.valid
    reference.io.virtual.request.bits := adapter.io.virtual.request.bits
    reference.io.virtual.requestMask := adapter.io.virtual.requestMask
    reference.io.virtual.response.ready := adapter.io.virtual.response.ready
    reference.io.vmState := adapter.io.vmState
    reference.io.privilege := adapter.io.privilege
    reference.io.pmpState := adapter.io.pmpState
    reference.io.translation.request.ready := adapter.io.translation.request.ready
    reference.io.translation.response.valid := adapter.io.translation.response.valid
    reference.io.translation.response.bits := adapter.io.translation.response.bits
    reference.io.physical.request.ready := adapter.io.physical.request.ready
    reference.io.physical.response.valid := adapter.io.physical.response.valid
    reference.io.physical.response.bits := adapter.io.physical.response.bits
    reference.io.physical.responseError := adapter.io.physical.responseError
    reference.io.physical.responsePageFault := adapter.io.physical.responsePageFault

    assert(adapter.io.idle === reference.io.idle, "S1 adapter idle cycle mismatch")
    assert(adapter.io.virtual.request.ready === reference.io.virtual.request.ready,
        "S1 adapter request ready cycle mismatch")
    assert(adapter.io.virtual.response.valid === reference.io.virtual.response.valid,
        "S1 adapter response valid cycle mismatch")
    when(adapter.io.virtual.response.valid) {
        assert(adapter.io.virtual.response.bits === reference.io.virtual.response.bits &&
            adapter.io.virtual.responseError === reference.io.virtual.responseError &&
            adapter.io.virtual.responsePageFault === reference.io.virtual.responsePageFault,
            "S1 adapter response payload mismatch")
    }
    assert(adapter.io.translation.request.valid === reference.io.translation.request.valid &&
        adapter.io.translation.response.ready === reference.io.translation.response.ready,
        "S1 adapter translation handshake cycle mismatch")
    when(adapter.io.translation.request.valid) {
        assert(adapter.io.translation.request.bits.asUInt === reference.io.translation.request.bits.asUInt,
            "S1 adapter translation context mismatch")
    }
    assert(adapter.io.physical.request.valid === reference.io.physical.request.valid &&
        adapter.io.physical.response.ready === reference.io.physical.response.ready,
        "S1 adapter physical handshake cycle mismatch")
    when(adapter.io.physical.request.valid) {
        assert(adapter.io.physical.request.bits === reference.io.physical.request.bits &&
            adapter.io.physical.requestMask === reference.io.physical.requestMask,
            "S1 adapter physical address or permission mask mismatch")
    }
}

object InstructionTranslationTransactionGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new InstructionTranslationTransactionGsim(args(1).toInt,
        args.drop(2).contains("aligned"), args.drop(2).contains("stream"),
        !args.drop(2).contains("no-turnover")), Array("--target-dir", args.head))
}
