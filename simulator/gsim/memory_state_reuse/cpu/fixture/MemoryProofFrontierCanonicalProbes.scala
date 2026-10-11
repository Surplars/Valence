package soc.core.ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils

object MemoryProofFrontierCanonicalProbes {
    def connect(out: CanonicalOverlapTrace, board: BoardSocTop, p: OooParams): Unit = {
        require(p.memoryEntries == 4 && p.tagBits == 64 && Set(4, 5, 6).contains(p.robBits))
        val b = board.platform.core.core.core.backend
        val l = b.lsu; val q = b.observationRequests.get; val stores = b.observationStores.get
        val a = board.platform.core.observationTranslation.get
        def tap[T <: Data](x: T): T = BoringUtils.bore(x)
        def request(to: CanonicalOverlapRequest, from: DecoupledIO[DataRequest]): Unit = {
            to.valid := tap(from.valid); to.ready := tap(from.ready); to.bits := tap(from.bits)
        }
        def response(to: CanonicalOverlapResponse, from: DecoupledIO[DataResponse]): Unit = {
            to.valid := tap(from.valid); to.ready := tap(from.ready); to.bits := tap(from.bits)
        }
        out.enabled := p.canonicalVirtualStoreOverlap.B; out.reset := tap(b.reset).asBool
        out.epoch := tap(b.io.loadPrecheck.get.epoch); out.stable := tap(b.io.loadPrecheck.get.stable)
        out.headValid := tap(b.ledger.io.headValid); out.headToken := tap(b.headRenamed.token)
        out.protectedValid := tap(b.memoryProtected); out.protectedToken := tap(b.memoryOwner)
        out.capture := 0.U.asTypeOf(out.capture); out.record := 0.U.asTypeOf(out.record)
        out.tracked := false.B; out.ownerLive := false.B; out.invalidate := false.B
        b.canonicalStoreTracker.foreach { t =>
            out.capture := tap(t.io.checked); out.record := tap(t.io.certificate)
            out.tracked := tap(t.io.tracked); out.ownerLive := tap(t.io.ownerLive)
            out.invalidate := tap(t.io.invalidate)
        }
        for ((to, i) <- out.slots.zipWithIndex) {
            val from = l.slots(i)
            to.live := tap(from.io.busy); to.token := tap(from.io.owner); to.phase := tap(from.io.phase)
            to.serial := !tap(l.parallel(i)); to.cancel := tap(l.io.cancel(i))
            to.requestAcceptedKnown := p.canonicalVirtualStoreOverlap.B
            to.requestAccepted := l.requestAccepted.map(x => tap(x(i))).getOrElse(false.B)
            to.certifiedStoreClass := l.certifiedStoreClass.map(x => tap(x(i))).getOrElse(false.B)
            to.exemptSerial := (if (p.canonicalVirtualStoreOverlap) tap(l.exemptSerial(i)) else false.B); response(to.response, from.io.memory.response)
        }
        out.startValid := tap(l.io.start.valid); out.startReady := tap(l.io.start.ready)
        val s = l.io.start.bits
        out.startToken := tap(s.token); out.startStore := tap(s.store); out.startAtomic := tap(s.atomic)
        out.startVirtual := tap(s.virtualized); out.startPrechecked := tap(s.precheckedLoad)
        out.startForwarded := tap(s.forward.valid); out.startEpoch := tap(s.translationEpoch)
        out.startVa := tap(s.address); out.startPa := tap(s.physicalAddress); out.startSize := tap(s.size)
        out.requestOwner := tap(l.io.requestOwner)
        request(out.request, q.io.enq); request(out.dequeue, q.io.deq)
        request(out.upstream, a.io.virtual.request)
        out.upstreamIntegerDirect := !tap(b.fpMemoryEpoch) && tap(stores.readStart)
        out.checked.valid := tap(a.checked.get.enq.valid); out.checked.ready := tap(a.checked.get.enq.ready)
        out.checked.bits := tap(a.checked.get.enq.bits.request)
        out.checkedFault := tap(a.checked.get.enq.bits.fault); out.checkedPageFault := tap(a.checked.get.enq.bits.pageFault)
        out.checkedDequeue.valid := tap(a.checked.get.deq.valid); out.checkedDequeue.ready := tap(a.checked.get.deq.ready)
        out.checkedDequeue.bits := tap(a.checked.get.deq.bits.request)
        out.ownerPush := tap(a.owners.io.enq.valid) && tap(a.owners.io.enq.ready); out.ownerFault := tap(a.owners.io.enq.bits.fault)
        request(out.physical, a.io.physical.request)
        response(out.physicalResponse, a.io.physical.response); response(out.upstreamResponse, a.io.virtual.response)
        // The legacy transient preparer is absent in the new ON graph.
        // Preserve exact legacy taps for OFF and expose only the actual selected
        // bank load proof for ON. Frontier winners have their own mp* event stream.
        if (!p.memoryProofFrontier) {
        val prepared = b.loadPreparation.get.io.prepared
        out.preparedValid := tap(prepared.valid); out.preparedToken := tap(prepared.bits.token)
        out.preparedAllowed := tap(prepared.bits.allowed); out.preparedEpoch := tap(prepared.bits.epoch)
        out.preparedVa := tap(prepared.bits.address); out.preparedPa := tap(prepared.bits.physicalAddress)
        out.preparedSize := tap(prepared.bits.size); out.preparedMatchesChoice := tap(b.preparedLoadMatches)
        } else {
            val prepared = b.proofFrontier.get.io.selectedProof
            out.preparedValid := tap(prepared.valid) && !tap(prepared.bits.payload.write)
            out.preparedToken := tap(prepared.bits.token)
            out.preparedAllowed := tap(prepared.valid) && !tap(prepared.bits.payload.write)
            out.preparedEpoch := tap(prepared.bits.epoch)
            out.preparedVa := tap(prepared.bits.payload.address)
            out.preparedPa := tap(prepared.bits.payload.physicalAddress)
            out.preparedSize := tap(prepared.bits.payload.size)
            out.preparedMatchesChoice := tap(b.preparedLoadMatches)
        }
        out.choiceValid := tap(b.memoryChoice.valid); out.choiceToken := tap(b.memoryEntry.renamed.token)
        out.choiceStore := tap(b.memoryEntry.request.store); out.choiceAtomic := tap(b.memoryEntry.request.atomic)
        out.choicePrechecked := tap(b.precheckedLoad); out.choiceIsHead := tap(b.memoryChoice.index) === tap(b.head)
        out.blockedByStore := tap(b.blockedByStore); out.physicalStoreConflict := tap(b.physicalStoreConflict)
        out.olderUncanonical := tap(b.olderUncanonicalMemory); out.olderSystem := tap(b.olderSystem)
        out.issueAvailable := tap(l.io.issueAvailable); out.noOtherSerial := tap(l.noOtherSerial)
    }
}
