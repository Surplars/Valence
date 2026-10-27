package soc.core.ooo

import chisel3._
import chisel3.util._

/** Immutable ownership key for a disposable, side-effect-free load preparation reservation. */
class ElasticVirtualRamLoadOwner(p: OooParams) extends VirtualRamLoadCandidate(p) {
    val epoch = UInt(32.W)
}

/** Narrow elastic alternative to VirtualRamLoadPreparation, selected only by its experiment flag.
  *
  * D holds one early second-rank VA descriptor; T and R retain the original lookup and physical
  * permission register boundaries. A current query has minimum latency two, a D capture minimum
  * latency three, with explicit retention/preemption stalls. Under the two-rank warm supply
  * contract the target result interval is two, not one. There is one hit-only peek and one result.
  * These reservations own no LSU, demand/walk, drain, result-queue, or bus credit.
  *
  * Credits use raw pre-edge occupancy: R consumption/expiry/cleanup cannot feed T credit, and D
  * transfer cannot feed D refill. Actual issue affects only selected-next-owner cancellation.
  * Wide payload enables use local empty/advance credit, not lookahead dedup or actual issue.
  * State is exactly D/T/R: 3 * (robBits + tagBits) + 428 bits, or 632 for ROB16/tag64.
  */
class ElasticVirtualRamLoadPreparation(p: OooParams) extends Module {
    require(p.virtualRamLoadPrecheck && p.elasticLoadProofSupply)

    val io = IO(new Bundle {
        // These sources are already ordinary-load/full-token/ready-qualified by the backend.
        val current = Input(Valid(new VirtualRamLoadCandidate(p)))
        val lookahead = Input(Valid(new VirtualRamLoadCandidate(p)))
        val issued = Input(Valid(new RobToken(p)))

        // Raw registered keys break the owner-output -> live-input combinational dependency.
        // Live inputs read only registered pending/generation/class/size metadata, never a late
        // issue, completion, killed mask, recovery decision, or planner.useSecond signal.
        val descriptorOwner = Output(Valid(new ElasticVirtualRamLoadOwner(p)))
        val translatedOwner = Output(Valid(new ElasticVirtualRamLoadOwner(p)))
        val preparedOwner = Output(Valid(new ElasticVirtualRamLoadOwner(p)))
        val descriptorOwnerLive = Input(Bool())
        val translatedOwnerLive = Input(Bool())
        val preparedOwnerLive = Input(Bool())

        val precheck = new VirtualLoadPrecheckPort
        val pmpState = Input(new PmpState)
        val privilege = Input(UInt(2.W))
        val flush = Input(Bool())
        val prepared = Output(Valid(new VirtualRamLoadCertificate(p)))
        val hit = Output(Bool())
    })

    val descriptorValid = RegInit(false.B)
    val descriptor = Reg(new ElasticVirtualRamLoadOwner(p))
    val translatedValid = RegInit(false.B)
    val translated = Reg(new VirtualRamLoadCertificate(p))
    val normalMemory = Reg(Bool())
    val preparedValid = RegInit(false.B)
    val prepared = Reg(new VirtualRamLoadCertificate(p))

    private def sameToken(left: RobToken, right: RobToken): Bool = left.asUInt === right.asUInt

    private def sameCandidate(left: VirtualRamLoadCandidate, right: VirtualRamLoadCandidate): Bool =
        sameToken(left.token, right.token) && left.address === right.address && left.size === right.size

    private def ownerKey(candidate: VirtualRamLoadCandidate, epoch: UInt): ElasticVirtualRamLoadOwner = {
        val key = Wire(new ElasticVirtualRamLoadOwner(p))
        key.token := candidate.token
        key.address := candidate.address
        key.size := candidate.size
        key.epoch := epoch
        key
    }

    private def sameKey(left: ElasticVirtualRamLoadOwner, right: ElasticVirtualRamLoadOwner): Bool =
        sameCandidate(left, right) && left.epoch === right.epoch

    val translatedKey = ownerKey(translated, translated.epoch)
    val preparedKey = ownerKey(prepared, prepared.epoch)
    val currentKey = ownerKey(io.current.bits, io.precheck.epoch)

    io.descriptorOwner.valid := descriptorValid
    io.descriptorOwner.bits := descriptor
    io.translatedOwner.valid := translatedValid
    io.translatedOwner.bits := translatedKey
    io.preparedOwner.valid := preparedValid
    io.preparedOwner.bits := preparedKey

    val enabled = !reset.asBool && io.precheck.stable && !io.flush
    val descriptorLiveFresh = descriptorValid && io.descriptorOwnerLive &&
        descriptor.epoch === io.precheck.epoch
    val translatedLiveFresh = translatedValid && io.translatedOwnerLive &&
        translated.epoch === io.precheck.epoch
    val preparedLiveFresh = preparedValid && io.preparedOwnerLive && prepared.epoch === io.precheck.epoch

    // A different address/size for an occupied full token is an inconsistency, not more work.
    // Its old owner and incoming copies are removed at the edge before a later retry.
    // A registered D snapshot may still make a disposable hit-only peek on that edge.
    private def conflicts(candidate: ValidIO[VirtualRamLoadCandidate], owner: VirtualRamLoadCandidate): Bool =
        candidate.valid && sameToken(candidate.bits.token, owner.token) && !sameCandidate(candidate.bits, owner)

    val descriptorInconsistent = descriptorValid &&
        (conflicts(io.current, descriptor) || conflicts(io.lookahead, descriptor))
    val translatedInconsistent = translatedValid &&
        (conflicts(io.current, translated) || conflicts(io.lookahead, translated))
    val preparedInconsistent = preparedValid &&
        (conflicts(io.current, prepared) || conflicts(io.lookahead, prepared))
    val currentTokenConflict = io.current.valid && (
        (descriptorValid && conflicts(io.current, descriptor)) ||
        (translatedValid && conflicts(io.current, translated)) ||
        (preparedValid && conflicts(io.current, prepared)))
    val lookaheadCurrentConflict = io.current.valid && io.lookahead.valid &&
        sameToken(io.current.bits.token, io.lookahead.bits.token) &&
        !sameCandidate(io.current.bits, io.lookahead.bits)

    val currentInDescriptor = io.current.valid && descriptorLiveFresh && sameKey(currentKey, descriptor)
    val currentInTranslated = io.current.valid && translatedLiveFresh && sameKey(currentKey, translatedKey)
    // Negative R is also a full-cycle reservation; expiration is never an early absence signal.
    val currentInPrepared = io.current.valid && preparedLiveFresh && sameKey(currentKey, preparedKey)
    val currentReserved = currentInDescriptor || currentInTranslated || currentInPrepared

    // Neither dead/stale cleanup, preemption, negative expiry nor actual issue creates credit.
    // Inconsistency is next-state cancellation, not an AGU -> payload-clock-enable path.
    val resultSpace = !preparedValid
    val translatedAdvance = translatedLiveFresh && resultSpace && enabled
    val translatedSpace = !translatedValid || translatedAdvance
    // Live lookahead VA/size must not select this registered query payload. A conflicting
    // lookahead may cause one side-effect-free peek, but descriptorBad cancels its exact
    // incoming T owner below before it can become a valid translated or prepared proof.
    val queryFromDescriptor = descriptorLiveFresh &&
        (currentInDescriptor || !io.current.valid || currentReserved)
    val queryFromCurrent = io.current.valid && !currentReserved && !currentTokenConflict
    val queryCandidate = Wire(new VirtualRamLoadCandidate(p))
    queryCandidate.token := Mux(queryFromDescriptor, descriptor.token, io.current.bits.token)
    queryCandidate.address := Mux(queryFromDescriptor, descriptor.address, io.current.bits.address)
    queryCandidate.size := Mux(queryFromDescriptor, descriptor.size, io.current.bits.size)
    val queryOffer = (queryFromCurrent || queryFromDescriptor) && translatedSpace && enabled
    val queryAccept = queryOffer &&
        (!io.precheck.response.valid || io.precheck.response.bits.epoch === io.precheck.epoch)
    val descriptorTransfer = queryAccept && queryFromDescriptor

    io.precheck.request.valid := queryOffer
    io.precheck.request.bits.address := queryCandidate.address
    io.precheck.request.bits.size := queryCandidate.size
    io.precheck.request.bits.write := false.B
    io.hit := queryOffer && io.precheck.response.valid && io.precheck.stable

    val lookaheadResidentToken =
        (descriptorValid && sameToken(io.lookahead.bits.token, descriptor.token)) ||
        (translatedValid && sameToken(io.lookahead.bits.token, translated.token)) ||
        (preparedValid && sameToken(io.lookahead.bits.token, prepared.token))
    val lookaheadAcceptedToken = queryAccept && sameToken(io.lookahead.bits.token, queryCandidate.token)
    val descriptorCapture = !descriptorValid && io.lookahead.valid && !lookaheadResidentToken &&
        !lookaheadAcceptedToken && !lookaheadCurrentConflict && enabled

    // Eager, clocked current priority: if current is missing or only in D, discard noncurrent
    // T/R owners, including a T owner tentatively advancing into empty R on this edge. This
    // cannot erase an unrelated current query replacing T, and creates no same-edge credit.
    // D never blocks a direct current query, so it needs no advisory preemption.
    val descriptorPreempt = false.B
    val currentNeedsQuery = io.current.valid && !currentInTranslated && !currentInPrepared
    val translatedPreempt = currentNeedsQuery && translatedValid &&
        !sameToken(io.current.bits.token, translated.token)
    val preparedPreempt = io.current.valid && !currentInPrepared && preparedValid &&
        !sameToken(io.current.bits.token, prepared.token)
    val negativeExpire = preparedValid && !prepared.allowed

    val descriptorBad = descriptorValid && (!io.descriptorOwnerLive ||
        descriptor.epoch =/= io.precheck.epoch || descriptorInconsistent)
    val translatedBad = translatedValid && (!io.translatedOwnerLive ||
        translated.epoch =/= io.precheck.epoch || translatedInconsistent)
    val preparedBad = preparedValid && (!io.preparedOwnerLive ||
        prepared.epoch =/= io.precheck.epoch || preparedInconsistent)

    // Keep the original registered T -> physical PMP/range -> registered R boundary.
    val checkedSize = Mux(translatedValid, translated.size, 0.U)
    val alignmentMask = MuxLookup(checkedSize, 7.U(3.W))(Seq(0.U -> 0.U, 1.U -> 1.U, 2.U -> 3.U))
    val pmp = Module(new PmpChecker(p.pmpEntries, naturalAlignedAccess = true))
    pmp.io.state := io.pmpState
    pmp.io.address := Cat(translated.physicalAddress(63, 3),
        translated.physicalAddress(2, 0) & ~alignmentMask)
    pmp.io.size := checkedSize
    pmp.io.privilege := io.privilege
    pmp.io.access := PmpAccess.read
    val translatedAllowed = normalMemory && !pmp.io.denied &&
        AlignedMemoryDisjoint.aligned(translated.address, translated.size) &&
        SpeculativeRamRange.contains(p, translated.physicalAddress, translated.size) &&
        translated.address(11, 0) === translated.physicalAddress(11, 0)

    // Build tentative destinations and source liveness independently before cancellation.
    // An old destination's dead owner never invalidates an unrelated replacement owner.
    val descriptorNext = WireDefault(descriptor)
    val descriptorTentativeValid = WireDefault(descriptorValid)
    when(!descriptorValid) {
        descriptorNext.token := io.lookahead.bits.token
        descriptorNext.address := io.lookahead.bits.address
        descriptorNext.size := io.lookahead.bits.size
        descriptorNext.epoch := io.precheck.epoch
    }
    when(descriptorTransfer) { descriptorTentativeValid := false.B }
    when(descriptorCapture) { descriptorTentativeValid := true.B }
    val descriptorSourceLive = Mux(descriptorCapture, io.lookahead.valid, io.descriptorOwnerLive)

    val translatedNext = WireDefault(translated)
    val normalMemoryNext = WireDefault(normalMemory)
    val translatedTentativeValid = WireDefault(translatedValid)
    when(translatedSpace) {
        translatedNext.token := queryCandidate.token
        translatedNext.address := queryCandidate.address
        translatedNext.size := queryCandidate.size
        translatedNext.physicalAddress := Mux(io.hit, io.precheck.response.bits.physicalAddress, 0.U)
        translatedNext.epoch := io.precheck.epoch
        translatedNext.allowed := false.B
        normalMemoryNext := io.hit && io.precheck.response.bits.pbmt === 0.U
    }
    when(translatedAdvance) { translatedTentativeValid := false.B }
    when(queryAccept) { translatedTentativeValid := true.B }
    val translatedSourceLive = Mux(queryAccept,
        Mux(queryFromDescriptor, io.descriptorOwnerLive, io.current.valid), io.translatedOwnerLive)

    val preparedNext = WireDefault(prepared)
    val preparedTentativeValid = WireDefault(preparedValid)
    when(resultSpace) {
        preparedNext := translated
        preparedNext.allowed := translatedAllowed
    }
    when(translatedAdvance) { preparedTentativeValid := true.B }
    val preparedSourceLive = Mux(translatedAdvance, io.translatedOwnerLive, io.preparedOwnerLive)

    private def cancelled(next: ElasticVirtualRamLoadOwner): Bool = {
        val issued = io.issued.valid && sameToken(io.issued.bits, next.token)
        val badDescriptor = (descriptorBad || descriptorPreempt) && sameToken(descriptor.token, next.token)
        val badTranslated = (translatedBad || translatedPreempt) && sameToken(translated.token, next.token)
        val badPrepared = (preparedBad || preparedPreempt) && sameToken(prepared.token, next.token)
        val expired = negativeExpire && sameKey(preparedKey, next)
        issued || badDescriptor || badTranslated || badPrepared || expired
    }

    val translatedNextKey = ownerKey(translatedNext, translatedNext.epoch)
    val preparedNextKey = ownerKey(preparedNext, preparedNext.epoch)
    val descriptorNextValid = descriptorTentativeValid && descriptorSourceLive && enabled &&
        descriptorNext.epoch === io.precheck.epoch && !cancelled(descriptorNext)
    val translatedNextValid = translatedTentativeValid && translatedSourceLive && enabled &&
        translatedNext.epoch === io.precheck.epoch && !cancelled(translatedNextKey)
    val preparedNextValid = preparedTentativeValid && preparedSourceLive && enabled &&
        preparedNext.epoch === io.precheck.epoch && !cancelled(preparedNextKey)

    descriptorValid := descriptorNextValid
    translatedValid := translatedNextValid
    preparedValid := preparedNextValid
    when(!descriptorValid) { descriptor := descriptorNext }
    when(translatedSpace) {
        translated := translatedNext
        normalMemory := normalMemoryNext
    }
    when(resultSpace) { prepared := preparedNext }

    // Actual issue is deliberately absent here. The backend retains its exact full key/read-
    // allowed match and final launch veto; ready-head fallback does not require this certificate.
    io.prepared.valid := preparedLiveFresh && enabled
    io.prepared.bits := prepared

    val nextOwners = Seq((descriptorNextValid, descriptorNext),
        (translatedNextValid, translatedNextKey), (preparedNextValid, preparedNextKey))
    for ((valid, key) <- nextOwners) {
        when(queryAccept && queryFromDescriptor && descriptorInconsistent) {
            assert(!valid || !sameToken(key.token, descriptor.token),
                "a conflicting descriptor peek must discard every next-state copy of its full owner")
        }
        when(translatedPreempt) {
            assert(!valid || !sameToken(key.token, translated.token), "preempted T must not resurrect in any stage")
        }
        when(preparedPreempt) {
            assert(!valid || !sameToken(key.token, prepared.token), "preempted R must not survive in any stage")
        }
        when(io.issued.valid) {
            assert(!valid || !sameToken(key.token, io.issued.bits), "actual issue cancels held and incoming copies")
        }
    }
    for (left <- nextOwners.indices; right <- (left + 1) until nextOwners.size) {
        assert(!(nextOwners(left)._1 && nextOwners(right)._1 &&
            sameToken(nextOwners(left)._2.token, nextOwners(right)._2.token)),
            "one full token cannot reserve two elastic proof positions")
    }
    when(descriptorCapture) {
        assert(!descriptorValid && !lookaheadResidentToken && !lookaheadAcceptedToken,
            "D uses raw-empty credit and deduplicates the same-edge accepted query")
    }
    when(queryAccept && !queryFromDescriptor) {
        assert(!currentTokenConflict, "an inconsistent occupied token must clear before direct retry")
    }
    when(translatedAdvance) { assert(!preparedValid, "R consumption is never same-edge transfer credit") }
}
