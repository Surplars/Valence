package ooo

import chisel3._
import soc.core.ooo._

/** Real caller pair with shared external stimulus, no reference-model feedback.
  * Full IO equality includes inactive payload for implementation equivalence.
  * The host's architectural oracle checks only offered/owned transactions.
  */
object SharedTwoWordFetchAdapterComparison {
    def apply(before: InstructionTranslationAdapter, p: OooParams, inject: Bool): InstructionTranslationAdapter = {
        require(!before.sharedTwoWordFetchPmp && p.alignedFetchSinglePage && p.alignedFetchPmp && p.pmpEntries == 16)
        val after = Module(new InstructionTranslationAdapter(p, sharedTwoWordFetchPmp = true))
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
        // Injection checks this comparator's rejection path, not a production source mutant.
        assert(after.io.asUInt === (before.io.asUInt ^ inject.asUInt), "shared two-word adapter full IO mismatch")
        after
    }
}
