package soc.core.ooo

import chisel3._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import _root_.ooo.{Lane1OwnerBackendProfile, PendingStoreProofBackendGsim, PostedBoardConfiguration}

/** Reuse the qualified decoded backend, real ROB/LSU, adapter and independent host.
  * The new checks are passive and do not grant production authority.
  */
class CanonicalStoreOwnerMapBackendGsim(shared: Boolean)
    extends PendingStoreProofBackendGsim(true, true, true, 2, 2, true, true, true, true, true, true, shared) {
    val ownerMap = IO(Output(UInt(p.robEntries.W)))
    val ownerLive = IO(Output(Bool()))
    val certificateValid = IO(Output(Bool()))
    val certificateIndex = IO(Output(UInt(p.robBits.W)))
    val certificateTag = IO(Output(UInt(p.tagBits.W)))
    require(p == Lane1OwnerBackendProfile.params(true).copy(
        directRank1MemorySourceIds = true, directRegisteredExecutionOperands = true,
        sharedCanonicalStoreOwnerMatch = shared))
    require(backend.shareCanonicalStoreOwnerMatch == shared)
    ownerMap := CanonicalStoreOwnerMapBackendCheck.attach(backend)
    val tracker = backend.canonicalStoreTracker.get
    ownerLive := BoringUtils.bore(tracker.io.ownerLive)
    val certificate = BoringUtils.bore(tracker.io.certificate)
    certificateValid := certificate.valid
    certificateIndex := certificate.bits.origin.token.index
    certificateTag := certificate.bits.origin.token.tag
}

