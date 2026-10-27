package soc.core.ooo

import chisel3._
import chisel3.util._

/** Optional three-rank advisory supply with two D rows, one T and two R rows.
  *
  * D capture -> registered TLB result -> registered physical permission -> use takes
  * three cycles; the existing current query bypasses only D and takes two. At most
  * one capture, query and permission transfer occurs per cycle. Rows own no execution,
  * walk, bus, response or drain credit. D/R admission uses only pre-edge empty rows;
  * issue, expiry, cleanup and victim eviction never grant same-edge free capacity.
  * T may advance and accept a new query, retaining both permission register boundaries.
  *
  * Current exact-key R selection and clocked single-victim eviction preserve progress
  * without erasing all ahead proofs. Both lookahead addresses remain independently
  * computed inputs, never sources for the actual execution address. The backend must
  * preserve registered-ready source immutability and its independent final VA check.
  */
class BufferedVirtualRamLoadPreparation(p: OooParams) extends Module {
    require(p.virtualRamLoadPrecheck && p.elasticLoadProofSupply && p.bufferedThirdRankLoadProof)

    val io = IO(new Bundle {
        val current = Input(Valid(new VirtualRamLoadCandidate(p)))
        // Existing second execution rank, then independent third/future advisory rank.
        val lookahead = Input(Vec(2, Valid(new VirtualRamLoadCandidate(p))))
        val issued = Input(Valid(new RobToken(p)))

        // Raw register keys: liveness must not depend on late issue/cancel/recovery.
        val descriptorOwner = Output(Vec(2, Valid(new ElasticVirtualRamLoadOwner(p))))
        val translatedOwner = Output(Valid(new ElasticVirtualRamLoadOwner(p)))
        val preparedOwner = Output(Vec(2, Valid(new ElasticVirtualRamLoadOwner(p))))
        // Index-only advisory exclusion, never a proof, live owner, permission or credit.
        val registeredExclusionMask =
            if (p.registeredAdvisoryExclusion) Some(Output(UInt(p.robEntries.W))) else None
        val descriptorOwnerLive = Input(Vec(2, Bool()))
        val translatedOwnerLive = Input(Bool())
        val preparedOwnerLive = Input(Vec(2, Bool()))

        val precheck = new VirtualLoadPrecheckPort
        val pmpState = Input(new PmpState)
        val privilege = Input(UInt(2.W))
        val flush = Input(Bool())
        val prepared = Output(Valid(new VirtualRamLoadCertificate(p)))
        val hit = Output(Bool())
    })

    val descriptorValid = RegInit(VecInit(Seq.fill(2)(false.B)))
    val descriptor = Reg(Vec(2, new ElasticVirtualRamLoadOwner(p)))
    val translatedValid = RegInit(false.B)
    val translated = Reg(new VirtualRamLoadCertificate(p))
    val normalMemory = Reg(Bool())
    val preparedValid = RegInit(VecInit(Seq.fill(2)(false.B)))
    val prepared = Reg(Vec(2, new VirtualRamLoadCertificate(p)))
    val descriptorTurn = RegInit(false.B)
    val preparedVictimTurn = RegInit(false.B)

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
    val preparedKeys = VecInit(prepared.map(row => ownerKey(row, row.epoch)))
    val currentKey = ownerKey(io.current.bits, io.precheck.epoch)
    val candidates = Seq(io.current, io.lookahead(0), io.lookahead(1))

    for (i <- 0 until 2) {
        io.descriptorOwner(i).valid := descriptorValid(i)
        io.descriptorOwner(i).bits := descriptor(i)
        io.preparedOwner(i).valid := preparedValid(i)
        io.preparedOwner(i).bits := preparedKeys(i)
    }
    io.translatedOwner.valid := translatedValid
    io.translatedOwner.bits := translatedKey

    val enabled = !reset.asBool && io.precheck.stable && !io.flush
    val descriptorLiveFresh = VecInit((0 until 2).map(i => descriptorValid(i) &&
        io.descriptorOwnerLive(i) && descriptor(i).epoch === io.precheck.epoch))
    val translatedLiveFresh = translatedValid && io.translatedOwnerLive &&
        translated.epoch === io.precheck.epoch
    val preparedLiveFresh = VecInit((0 until 2).map(i => preparedValid(i) &&
        io.preparedOwnerLive(i) && prepared(i).epoch === io.precheck.epoch))

    // Epoch changes are freshness cleanup, not VA/size conflicts. Incoming conflict
    // checks also cover newly queried/captured owners with no prior occupied row.
    private def conflicts(candidate: ValidIO[VirtualRamLoadCandidate], owner: VirtualRamLoadCandidate): Bool =
        candidate.valid && sameToken(candidate.bits.token, owner.token) && !sameCandidate(candidate.bits, owner)
    private def inputConflict(owner: VirtualRamLoadCandidate): Bool =
        candidates.map(candidate => conflicts(candidate, owner)).reduce(_ || _)

    val descriptorInconsistent = VecInit((0 until 2).map(i =>
        descriptorValid(i) && inputConflict(descriptor(i))))
    val translatedInconsistent = translatedValid && inputConflict(translated)
    val preparedInconsistent = VecInit((0 until 2).map(i =>
        preparedValid(i) && inputConflict(prepared(i))))
    val currentTokenConflict =
        (0 until 2).map(i => descriptorValid(i) && conflicts(io.current, descriptor(i))).reduce(_ || _) ||
        (translatedValid && conflicts(io.current, translated)) ||
        (0 until 2).map(i => preparedValid(i) && conflicts(io.current, prepared(i))).reduce(_ || _)

    val currentDescriptorMatches = VecInit((0 until 2).map(i =>
        io.current.valid && descriptorLiveFresh(i) && sameKey(currentKey, descriptor(i))))
    val currentPreparedMatches = VecInit((0 until 2).map(i =>
        io.current.valid && preparedLiveFresh(i) && sameKey(currentKey, preparedKeys(i))))
    val currentInDescriptor = currentDescriptorMatches.asUInt.orR
    val currentInTranslated = io.current.valid && translatedLiveFresh && sameKey(currentKey, translatedKey)
    // A negative exact current row reserves the token for its complete registered cycle.
    val currentInPrepared = currentPreparedMatches.asUInt.orR
    val currentReserved = currentInDescriptor || currentInTranslated || currentInPrepared

    val descriptorEmpty = VecInit(descriptorValid.map(valid => !valid))
    val resultEmpty = VecInit(preparedValid.map(valid => !valid))
    val descriptorSpace = descriptorEmpty.asUInt.orR
    val resultSpace = resultEmpty.asUInt.orR
    val descriptorCaptureIndex = PriorityEncoder(descriptorEmpty.asUInt)
    val preparedInsertIndex = PriorityEncoder(resultEmpty.asUInt)
    val translatedAdvance = translatedLiveFresh && resultSpace && enabled
    val translatedSpace = !translatedValid || translatedAdvance

    val descriptorRoundRobinIndex = Mux(descriptorLiveFresh(descriptorTurn.asUInt),
        descriptorTurn.asUInt, (!descriptorTurn).asUInt)
    val queryDescriptorIndex = Mux(currentInDescriptor,
        PriorityEncoder(currentDescriptorMatches.asUInt), descriptorRoundRobinIndex)
    val queryFromDescriptor = descriptorLiveFresh(queryDescriptorIndex) &&
        (currentInDescriptor || !io.current.valid || currentReserved)
    val queryFromCurrent = io.current.valid && !currentReserved && !currentTokenConflict
    val queryCandidate = Wire(new VirtualRamLoadCandidate(p))
    queryCandidate.token := Mux(queryFromDescriptor, descriptor(queryDescriptorIndex).token, io.current.bits.token)
    queryCandidate.address := Mux(queryFromDescriptor,
        descriptor(queryDescriptorIndex).address, io.current.bits.address)
    queryCandidate.size := Mux(queryFromDescriptor, descriptor(queryDescriptorIndex).size, io.current.bits.size)
    val queryOffer = (queryFromDescriptor || queryFromCurrent) && translatedSpace && enabled
    val queryAccept = queryOffer &&
        (!io.precheck.response.valid || io.precheck.response.bits.epoch === io.precheck.epoch)
    val descriptorTransfer = queryAccept && queryFromDescriptor

    io.precheck.request.valid := queryOffer
    io.precheck.request.bits.address := queryCandidate.address
    io.precheck.request.bits.size := queryCandidate.size
    io.precheck.request.bits.write := false.B
    // Diagnostic hit is not acceptance/authority; response epoch gates queryAccept.
    io.hit := queryOffer && io.precheck.response.valid && io.precheck.stable

    private def residentToken(token: RobToken): Bool =
        (0 until 2).map(i => descriptorValid(i) && sameToken(token, descriptor(i).token)).reduce(_ || _) ||
        (translatedValid && sameToken(token, translated.token)) ||
        (0 until 2).map(i => preparedValid(i) && sameToken(token, prepared(i).token)).reduce(_ || _)

    // Selection depends on full tokens, not lookahead VA conflicts or actual issue.
    // A nominal capture may be cancelled below; that cancellation is never free credit.
    val lookaheadAvailable = VecInit(io.lookahead.map(candidate => candidate.valid &&
        !residentToken(candidate.bits.token) &&
        !(queryAccept && sameToken(candidate.bits.token, queryCandidate.token))))
    val captureLookaheadIndex = PriorityEncoder(lookaheadAvailable.asUInt)
    val captureCandidate = io.lookahead(captureLookaheadIndex)
    val captureKey = ownerKey(captureCandidate.bits, io.precheck.epoch)
    val descriptorCapture = descriptorSpace && lookaheadAvailable.asUInt.orR && enabled

    if (p.registeredAdvisoryExclusion) {
        require(p.robEntries == 16, "registered advisory exclusion is qualified only for ROB16")
        // One-cycle observation, not accumulated history: raw pre-edge owners plus
        // nominal new owners. Late issue/conflict/expiry cancellation must not enter
        // this update. In particular, do not substitute the final next-valid rows.
        def ownerIndexMask(valid: Bool, token: RobToken): UInt =
            Mux(valid, UIntToOH(token.index, p.robEntries), 0.U(p.robEntries.W))
        val rawOwnerMask = (
            (0 until 2).map(i => ownerIndexMask(descriptorValid(i), descriptor(i).token)) ++
                Seq(ownerIndexMask(translatedValid, translated.token)) ++
                (0 until 2).map(i => ownerIndexMask(preparedValid(i), prepared(i).token))
        ).reduce(_ | _)
        val nominalQueryMask = ownerIndexMask(queryAccept, queryCandidate.token)
        val nominalCaptureMask = ownerIndexMask(descriptorCapture, captureCandidate.bits.token)
        val exclusionMaskNext = rawOwnerMask | nominalQueryMask | nominalCaptureMask
        val exclusionMask = RegInit(0.U(p.robEntries.W))
        exclusionMask := exclusionMaskNext
        io.registeredExclusionMask.get := exclusionMask

        // This containment invariant is supplementary: the independent cycle oracle
        // must also check exact next-mask equality and no-contribution clearing.
        // No shadow history registers are added just for that oracle.
        assert(!(rawOwnerMask & ~exclusionMask).orR,
            "every raw buffered owner index must be conservatively excluded")
    }

    val preparedVictimIndex = preparedVictimTurn.asUInt
    val preparedPreempt = io.current.valid && !currentInPrepared && !resultSpace && enabled
    val negativeExpireRows = VecInit((0 until 2).map(i => preparedValid(i) && !prepared(i).allowed))
    val negativeExpire = negativeExpireRows.asUInt.orR
    val descriptorBad = VecInit((0 until 2).map(i => descriptorValid(i) &&
        (!io.descriptorOwnerLive(i) || descriptor(i).epoch =/= io.precheck.epoch || descriptorInconsistent(i))))
    val translatedBad = translatedValid &&
        (!io.translatedOwnerLive || translated.epoch =/= io.precheck.epoch || translatedInconsistent)
    val preparedBad = VecInit((0 until 2).map(i => preparedValid(i) &&
        (!io.preparedOwnerLive(i) || prepared(i).epoch =/= io.precheck.epoch || preparedInconsistent(i))))

    // Exactly the existing registered-T physical permission calculation.
    val checkedSize = Mux(translatedValid, translated.size, 0.U)
    val alignmentMask = MuxLookup(checkedSize, 7.U(3.W))(Seq(0.U -> 0.U, 1.U -> 1.U, 2.U -> 3.U))
    val pmpDenied = NaturalPmpEvaluation.denied(p.pmpEntries, p.decodedNaturalPmp,
        p.sharedLoadProofPmpBounds, io.pmpState,
        Cat(translated.physicalAddress(63, 3), translated.physicalAddress(2, 0) & ~alignmentMask),
        checkedSize, io.privilege, PmpAccess.read)
    val translatedAllowed = normalMemory && !pmpDenied &&
        AlignedMemoryDisjoint.aligned(translated.address, translated.size) &&
        SpeculativeRamRange.contains(p, translated.physicalAddress, translated.size) &&
        translated.address(11, 0) === translated.physicalAddress(11, 0)

    val descriptorNext = WireDefault(descriptor)
    val descriptorTentativeValid = WireDefault(descriptorValid)
    val descriptorSourceLive = WireDefault(io.descriptorOwnerLive)
    for (i <- 0 until 2) {
        when(descriptorSpace && descriptorCaptureIndex === i.U) {
            descriptorNext(i) := captureKey
        }
        when(descriptorTransfer && queryDescriptorIndex === i.U) { descriptorTentativeValid(i) := false.B }
        when(descriptorCapture && descriptorCaptureIndex === i.U) {
            descriptorTentativeValid(i) := true.B
            descriptorSourceLive(i) := captureCandidate.valid
        }
    }

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
        Mux(queryFromDescriptor, io.descriptorOwnerLive(queryDescriptorIndex), io.current.valid),
        io.translatedOwnerLive)

    val preparedNext = WireDefault(prepared)
    val preparedTentativeValid = WireDefault(preparedValid)
    val preparedSourceLive = WireDefault(io.preparedOwnerLive)
    for (i <- 0 until 2) {
        when(resultSpace && preparedInsertIndex === i.U) {
            preparedNext(i) := translated
            preparedNext(i).allowed := translatedAllowed
        }
        when(translatedAdvance && preparedInsertIndex === i.U) {
            preparedTentativeValid(i) := true.B
            preparedSourceLive(i) := io.translatedOwnerLive
        }
    }

    private def cancelled(next: ElasticVirtualRamLoadOwner): Bool = {
        val issued = io.issued.valid && sameToken(io.issued.bits, next.token)
        val badD = (0 until 2).map(i => descriptorBad(i) && sameToken(descriptor(i).token, next.token)).reduce(_ || _)
        val badT = translatedBad && sameToken(translated.token, next.token)
        val badR = (0 until 2).map(i => preparedBad(i) && sameToken(prepared(i).token, next.token)).reduce(_ || _)
        val expired = (0 until 2).map(i => negativeExpireRows(i) && sameKey(preparedKeys(i), next)).reduce(_ || _)
        val victim = preparedPreempt && sameToken(prepared(preparedVictimIndex).token, next.token)
        issued || badD || badT || badR || expired || victim || inputConflict(next)
    }

    val translatedNextKey = ownerKey(translatedNext, translatedNext.epoch)
    val preparedNextKeys = VecInit(preparedNext.map(row => ownerKey(row, row.epoch)))
    val (descriptorNextValid, translatedNextValid, preparedNextValid) =
        if (p.sourceLocalLoadProofCancellation) {
            // Cancellation belongs to the pre-edge SOURCE, not the destination row.
            // Valid old rows have unique full tokens: another bad/expired/victim
            // owner cannot cancel a retained or transferred source. Keep the wide
            // payload enables and raw-empty credits above entirely unchanged.
            val descriptorKeep = VecInit((0 until 2).map(i =>
                descriptorLiveFresh(i) && enabled && !descriptorInconsistent(i) &&
                    !(io.issued.valid && sameToken(io.issued.bits, descriptor(i).token))))
            val translatedKeep = translatedLiveFresh && enabled && !translatedInconsistent &&
                !(io.issued.valid && sameToken(io.issued.bits, translated.token))
            val preparedKeep = VecInit((0 until 2).map(i =>
                preparedLiveFresh(i) && enabled && !preparedInconsistent(i) && prepared(i).allowed &&
                    !(preparedPreempt && preparedVictimIndex === i.U) &&
                    !(io.issued.valid && sameToken(io.issued.bits, prepared(i).token))))

            // Current is NOT guaranteed absent from raw rows: a dead/stale exact
            // raw owner is not currentReserved. Retain its complete generic
            // cancellation, including old bad/expired/victim identities.
            val currentKeep = io.current.valid && enabled && !cancelled(currentKey)
            val queryKeep = Mux(queryFromDescriptor,
                descriptorKeep(queryDescriptorIndex), currentKeep)
            // A nominal capture excludes every raw resident token and the nominal
            // query. Incoming conflicts and issue still cancel it at this edge;
            // that cancellation must not create capacity or alter exclusionMask.
            val captureKeep = captureCandidate.valid && enabled && !inputConflict(captureKey) &&
                !(io.issued.valid && sameToken(io.issued.bits, captureKey.token))
            val nextD = VecInit((0 until 2).map(i =>
                Mux(descriptorCapture && descriptorCaptureIndex === i.U, captureKeep,
                    descriptorKeep(i) && !(descriptorTransfer && queryDescriptorIndex === i.U))))
            val nextT = Mux(queryAccept, queryKeep, translatedKeep && !translatedAdvance)
            val nextR = VecInit((0 until 2).map(i =>
                Mux(translatedAdvance && preparedInsertIndex === i.U, translatedKeep, preparedKeep(i))))
            (nextD, nextT, nextR)
        } else {
            val nextD = VecInit((0 until 2).map(i => descriptorTentativeValid(i) &&
                descriptorSourceLive(i) && enabled && descriptorNext(i).epoch === io.precheck.epoch &&
                !cancelled(descriptorNext(i))))
            val nextT = translatedTentativeValid && translatedSourceLive && enabled &&
                translatedNext.epoch === io.precheck.epoch && !cancelled(translatedNextKey)
            val nextR = VecInit((0 until 2).map(i => preparedTentativeValid(i) &&
                preparedSourceLive(i) && enabled && preparedNext(i).epoch === io.precheck.epoch &&
                !cancelled(preparedNextKeys(i))))
            (nextD, nextT, nextR)
        }

    descriptorValid := descriptorNextValid
    translatedValid := translatedNextValid
    preparedValid := preparedNextValid
    for (i <- 0 until 2) {
        when(descriptorSpace && descriptorCaptureIndex === i.U) { descriptor(i) := descriptorNext(i) }
        when(resultSpace && preparedInsertIndex === i.U) { prepared(i) := preparedNext(i) }
    }
    when(translatedSpace) {
        translated := translatedNext
        normalMemory := normalMemoryNext
    }
    when(descriptorTransfer) { descriptorTurn := !queryDescriptorIndex.asBool }
    when(preparedPreempt) { preparedVictimTurn := !preparedVictimIndex.asBool }

    val selectedPreparedIndex = PriorityEncoder(currentPreparedMatches.asUInt)
    io.prepared.valid := currentInPrepared && enabled
    io.prepared.bits := prepared(selectedPreparedIndex)

    val nextOwners = (0 until 2).map(i => (descriptorNextValid(i), descriptorNext(i))) ++
        Seq((translatedNextValid, translatedNextKey)) ++
        (0 until 2).map(i => (preparedNextValid(i), preparedNextKeys(i)))
    for ((valid, key) <- nextOwners) {
        when(io.issued.valid) {
            assert(!valid || !sameToken(key.token, io.issued.bits), "issue cancels every held and incoming full owner")
        }
        when(preparedPreempt) {
            assert(!valid || !sameToken(key.token, prepared(preparedVictimIndex).token),
                "a clock-evicted result owner must not resurrect in another row")
        }
        when(inputConflict(key)) {
            assert(!valid, "conflicting independently supplied VA/size cancels the tentative owner")
        }
    }
    for (left <- nextOwners.indices; right <- (left + 1) until nextOwners.size) {
        assert(!(nextOwners(left)._1 && nextOwners(right)._1 &&
            sameToken(nextOwners(left)._2.token, nextOwners(right)._2.token)),
            "one full token cannot occupy multiple buffered proof rows")
    }
    when(descriptorCapture) {
        assert(!descriptorValid(descriptorCaptureIndex) && captureCandidate.valid &&
            !residentToken(captureCandidate.bits.token) &&
            !(queryAccept && sameToken(captureCandidate.bits.token, queryCandidate.token)),
            "D capture requires raw-empty space and full-token deduplication")
    }
    when(descriptorCapture && descriptorTransfer) {
        assert(descriptorCaptureIndex =/= queryDescriptorIndex,
            "a transferred D row cannot grant same-edge capture credit")
    }
    when(translatedAdvance) {
        assert(!preparedValid(preparedInsertIndex), "R issue/expiry/victim cannot grant same-edge advance credit")
    }
    when(io.prepared.valid) {
        assert(io.current.valid && sameKey(currentKey, preparedKeys(selectedPreparedIndex)),
            "only an exact independent current key can select a buffered certificate")
    }
}
