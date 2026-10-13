package ooo

import chisel3._
import soc.core.ooo._

/** Cycle-exact protocol and complete owned-payload comparison of real adapters.
  * Only idle payload bits may differ. All external stimulus is shared; neither
  * adapter supplies a translation or memory oracle for the other.
  */
object FetchReadyDataClearComparison {
    def apply(before: InstructionTranslationAdapter, p: OooParams): Bool = {
        require(!p.fetchReadyDataClear && p.registeredTranslationHeads)
        val after = Module(new InstructionTranslationAdapter(p.copy(fetchReadyDataClear = true)))
        after.io.virtual.request.valid := before.io.virtual.request.valid
        after.io.virtual.request.bits := before.io.virtual.request.bits
        after.io.virtual.requestMask := before.io.virtual.requestMask
        after.io.virtual.response.ready := before.io.virtual.response.ready
        after.io.vmState := before.io.vmState
        after.io.privilege := before.io.privilege
        after.io.pmpState := before.io.pmpState
        after.io.translation.request.ready := before.io.translation.request.ready
        after.io.translation.response.valid := before.io.translation.response.valid
        after.io.translation.response.bits := before.io.translation.response.bits
        after.io.physical.request.ready := before.io.physical.request.ready
        after.io.physical.response.valid := before.io.physical.response.valid
        after.io.physical.response.bits := before.io.physical.response.bits
        after.io.physical.responseError := before.io.physical.responseError
        after.io.physical.responsePageFault := before.io.physical.responsePageFault

        assert(after.io.idle === before.io.idle, "ready-clear changed idle ownership")
        assert(after.io.virtual.request.ready === before.io.virtual.request.ready,
            "ready-clear changed virtual admission")
        assert(after.io.virtual.response.valid === before.io.virtual.response.valid,
            "ready-clear changed virtual response timing")
        assert(after.io.translation.request.valid === before.io.translation.request.valid &&
            after.io.translation.response.ready === before.io.translation.response.ready,
            "ready-clear changed translation handshakes")
        assert(after.io.physical.request.valid === before.io.physical.request.valid &&
            after.io.physical.response.ready === before.io.physical.response.ready,
            "ready-clear changed physical handshakes")
        when(before.io.translation.request.valid) {
            assert(after.io.translation.request.bits.asUInt === before.io.translation.request.bits.asUInt,
                "ready-clear changed translation owner/context")
        }
        when(before.io.physical.request.valid) {
            assert(after.io.physical.request.bits === before.io.physical.request.bits &&
                after.io.physical.requestMask === before.io.physical.requestMask,
                "ready-clear changed physical address/mask")
        }
        when(!before.io.idle) {
            assert(after.io.virtual.response.bits === before.io.virtual.response.bits,
                "ready-clear changed complete owned data")
        }
        when(before.io.virtual.response.valid) {
            assert(after.io.virtual.responseError === before.io.virtual.responseError &&
                after.io.virtual.responsePageFault === before.io.virtual.responsePageFault,
                "ready-clear changed held response fault metadata")
        }
        before.io.idle && after.io.virtual.response.bits =/= before.io.virtual.response.bits
    }
}
