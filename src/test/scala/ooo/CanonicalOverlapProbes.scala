package soc.core.ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils

/** Passive, scalar leaves on both OFF and ON. No input, handshake, owner, or permission is added. */
class CanonicalOverlapRequest extends Bundle {
    val valid = Bool(); val ready = Bool(); val bits = new DataRequest
}
class CanonicalOverlapResponse extends Bundle {
    val valid = Bool(); val ready = Bool(); val bits = new DataResponse
}
class CanonicalOverlapSlot(p: OooParams) extends Bundle {
    val live = Bool(); val token = new RobToken(p); val phase = UInt(2.W)
    val serial = Bool(); val requestAcceptedKnown = Bool(); val requestAccepted = Bool()
    val certifiedStoreClass = Bool(); val exemptSerial = Bool(); val cancel = Bool()
    val response = new CanonicalOverlapResponse
}
class CanonicalOverlapTrace(p: OooParams) extends Bundle {
    val enabled = Bool(); val reset = Bool(); val epoch = UInt(32.W); val stable = Bool()
    val headValid = Bool(); val headToken = new RobToken(p)
    val protectedValid = Bool(); val protectedToken = new RobToken(p)
    val capture = Valid(new CanonicalStoreCertificate(p))
    val record = Valid(new CanonicalStoreCertificate(p))
    val tracked = Bool(); val ownerLive = Bool(); val invalidate = Bool()
    val slot0 = new CanonicalOverlapSlot(p); val slot1 = new CanonicalOverlapSlot(p)
    val slot2 = new CanonicalOverlapSlot(p); val slot3 = new CanonicalOverlapSlot(p)
    def slots: Seq[CanonicalOverlapSlot] = Seq(slot0, slot1, slot2, slot3)
    val startValid = Bool(); val startReady = Bool(); val startToken = new RobToken(p)
    val startStore = Bool(); val startAtomic = Bool(); val startVirtual = Bool()
    val startPrechecked = Bool(); val startForwarded = Bool(); val startEpoch = UInt(32.W)
    val startVa = UInt(64.W); val startPa = UInt(64.W); val startSize = UInt(2.W)
    val requestOwner = Valid(new RobToken(p))
    val request = new CanonicalOverlapRequest; val dequeue = new CanonicalOverlapRequest
    val upstream = new CanonicalOverlapRequest; val upstreamIntegerDirect = Bool()
    val checked = new CanonicalOverlapRequest; val checkedFault = Bool(); val checkedPageFault = Bool()
    val checkedDequeue = new CanonicalOverlapRequest; val ownerPush = Bool(); val ownerFault = Bool()
    val physical = new CanonicalOverlapRequest
    val physicalResponse = new CanonicalOverlapResponse; val upstreamResponse = new CanonicalOverlapResponse
    val preparedValid = Bool(); val preparedToken = new RobToken(p)
    val preparedAllowed = Bool(); val preparedEpoch = UInt(32.W)
    val preparedVa = UInt(64.W); val preparedPa = UInt(64.W); val preparedSize = UInt(2.W)
    val preparedMatchesChoice = Bool()
    val choiceValid = Bool(); val choiceToken = new RobToken(p); val choiceStore = Bool()
    val choiceAtomic = Bool(); val choicePrechecked = Bool(); val choiceIsHead = Bool()
    val blockedByStore = Bool(); val physicalStoreConflict = Bool(); val olderUncanonical = Bool()
    val issueAvailable = Bool(); val noOtherSerial = Bool(); val olderSystem = Bool()
}
object CanonicalOverlapProbes {
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
        val prepared = b.loadPreparation.get.io.prepared
        out.preparedValid := tap(prepared.valid); out.preparedToken := tap(prepared.bits.token)
        out.preparedAllowed := tap(prepared.bits.allowed); out.preparedEpoch := tap(prepared.bits.epoch)
        out.preparedVa := tap(prepared.bits.address); out.preparedPa := tap(prepared.bits.physicalAddress)
        out.preparedSize := tap(prepared.bits.size); out.preparedMatchesChoice := tap(b.preparedLoadMatches)
        out.choiceValid := tap(b.memoryChoice.valid); out.choiceToken := tap(b.memoryEntry.renamed.token)
        out.choiceStore := tap(b.memoryEntry.request.store); out.choiceAtomic := tap(b.memoryEntry.request.atomic)
        out.choicePrechecked := tap(b.precheckedLoad); out.choiceIsHead := tap(b.memoryChoice.index) === tap(b.head)
        out.blockedByStore := tap(b.blockedByStore); out.physicalStoreConflict := tap(b.physicalStoreConflict)
        out.olderUncanonical := tap(b.olderUncanonicalMemory); out.olderSystem := tap(b.olderSystem)
        out.issueAvailable := tap(l.io.issueAvailable); out.noOtherSerial := tap(l.noOtherSerial)
    }
}
