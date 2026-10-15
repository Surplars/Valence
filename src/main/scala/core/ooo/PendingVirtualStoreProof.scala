package soc.core.ooo

import chisel3._
import chisel3.util._

/** The existing saved address of a still-pending ordinary store. No data/accepted ownership. */
class PendingStoreProofOwner(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    val address = UInt(64.W)
    val size = UInt(3.W)
    val mask = UInt(8.W)
}

/** One/two/three bounded retained write certificates, sharing one hit-only query and one registered PMP
  * checker with the original load preparation. Target: one query/cycle, load/store fairness
  * within two available selection cycles and two query-to-proof register boundaries.
  * The optional registered query adds one selection-to-query boundary. Proof storage
  * grants no memory ownership; bound rows survive until exact actual-store capture or kill.
  */
class PendingVirtualStoreProof(p: OooParams, val registerQuery: Boolean,
    val exposeLoadPreparedCandidate: Boolean, val checkBindPlanning: Boolean = false) extends Module {
    // Keep the original unstaged constructor for production users and compiled fixtures.
    // The explicit switch retains the unstaged query path for isolated A/B qualification.
    def this(p: OooParams) = this(p, false, false)
    def this(p: OooParams, registerQuery: Boolean) = this(p, registerQuery, false)
    require(p.pendingVirtualStoreProof)
    private val rows = p.pendingVirtualStoreProofSlots
    require(rows != 3 || registerQuery, "third proof row requires the actual registered query implementation")
    private val rowBits = math.max(1, log2Ceil(rows))
    val io = IO(new Bundle {
        val head = Input(UInt(p.robBits.W))
        val owners = Input(Vec(p.robEntries, Valid(new PendingStoreProofOwner(p))))
        val queryEligible = Input(UInt(p.robEntries.W)) // Required older stores of the selected blocked load only.
        val clearOwners = Input(UInt(p.robEntries.W))
        val pause = Input(Bool())
        val flushQueries = Input(Bool())
        val loadCandidate = Input(Valid(new VirtualRamLoadCandidate(p)))
        val loadPrepared = Output(Valid(new VirtualRamLoadCertificate(p)))
        // Candidate only: final admission must still reject flushQueries. No new storage.
        val loadPreparedCandidateValid = if (exposeLoadPreparedCandidate) Some(Output(Bool())) else None
        val precheck = new VirtualLoadPrecheckPort
        val pmpState = Input(new PmpState)
        val privilege = Input(UInt(2.W))
        val bind = Input(UInt(rows.W))
        val consume = Input(Valid(new RobToken(p)))
        val proofs = Output(Vec(rows, Valid(new MemoryAddressProof(p))))
        val bound = Output(UInt(rows.W))
        val reservedCount = Output(UInt(2.W))
        val provedCount = Output(UInt(2.W))
    })
    val free :: queued :: inflight :: proved :: Nil = Enum(4)
    val state = RegInit(VecInit(Seq.fill(rows)(free)))
    val records = Reg(Vec(rows, new MemoryAddressProof(p)))
    val bound = RegInit(VecInit(Seq.fill(rows)(false.B)))
    def oldest(mask: UInt): UInt = {
        val after = mask & VecInit((0 until p.robEntries).map(i => i.U >= io.head)).asUInt
        OHToUInt(PriorityEncoderOH(Mux(after.orR, after, mask)))
    }
    def ownerMatches(proof: MemoryAddressProof): Bool = {
        val owner = io.owners(proof.token.index)
        owner.valid && owner.bits.token.asUInt === proof.token.asUInt &&
            owner.bits.address === proof.payload.address && owner.bits.size === proof.payload.size &&
            owner.bits.mask === proof.payload.mask && proof.payload.write
    }
    def consumed(proof: MemoryAddressProof): Bool =
        io.consume.valid && io.consume.bits.asUInt === proof.token.asUInt
    def sameDescriptor(a: MemoryAddressProof, b: MemoryAddressProof): Bool =
        a.token.asUInt === b.token.asUInt && a.epoch === b.epoch &&
            a.payload.address === b.payload.address && a.payload.size === b.payload.size &&
            a.payload.mask === b.payload.mask && a.payload.write === b.payload.write
    val rowOwnerMatches = VecInit(records.map(ownerMatches))
    def ownerCleared(row: Int): Bool = io.clearOwners(records(row).token.index) ||
        !rowOwnerMatches(row) || consumed(records(row))
    val epochStable = io.precheck.stable
    val cancelQueries = io.flushQueries || !epochStable
    val liveRows = VecInit((0 until rows).map(r => state(r) === proved && rowOwnerMatches(r) &&
        records(r).epoch === io.precheck.epoch && epochStable))
    val presentOwners = (0 until rows).map(r => Mux(state(r) =/= free,
        UIntToOH(records(r).token.index, p.robEntries), 0.U(p.robEntries.W))).reduce(_ | _)
    val eligible = VecInit(io.owners.zipWithIndex.map { case (owner, i) =>
        owner.valid && owner.bits.token.index === i.U
    }).asUInt & ~io.clearOwners
    val queryMask = eligible & io.queryEligible & ~presentOwners
    val admitIndex = oldest(queryMask)
    val empty = VecInit(state.map(_ === free)).asUInt
    val mayQuery = epochStable && !io.pause && !io.flushQueries
    val admission = mayQuery && queryMask.orR && empty.orR
    val admittedRow = PriorityEncoder(empty)
    if (rows == 3) {
        when(admission) { assert(admittedRow < rows.U, "admitted proof row index must be valid") }
        for (a <- 0 until rows; b <- 0 until a) {
            when(state(a) =/= free && state(b) =/= free) {
                assert(records(a).token.index =/= records(b).token.index,
                    "nonfree proof rows must have distinct owner indices")
            }
        }
    }
    // Eviction is a separate edge. Never replace a queued, inflight, or bound proof.
    val evictable = (0 until rows).map(r => state(r) === proved && !bound(r) &&
        (records(r).token.index - io.head) > (admitIndex - io.head))
    val victim = (0 until rows).map(r => (evictable(r), r.U(rowBits.W), records(r).token.index - io.head))
        .reduce { (a, b) => (a._1 || b._1,
            Mux(a._1 && (!b._1 || a._3 > b._3), a._2, b._2),
            Mux(a._1 && (!b._1 || a._3 > b._3), a._3, b._3)) }._2
    val evict = mayQuery && queryMask.orR && !empty.orR && evictable.reduce(_ || _)
    if (rows == 3) {
        when(evict) { assert(victim < rows.U, "evicted proof row index must be valid") }
    }
    if (checkBindPlanning) {
        when(io.bind.orR) {
            assert(!admission && !evict,
                "actual relied-row binding excludes simultaneous missing-store query admission or eviction")
        }
    }
    when(admission) {
        val owner = io.owners(admitIndex).bits
        state(admittedRow) := queued
        records(admittedRow).token := owner.token
        records(admittedRow).epoch := io.precheck.epoch
        records(admittedRow).payload.address := owner.address
        records(admittedRow).payload.physicalAddress := 0.U
        records(admittedRow).payload.write := true.B
        records(admittedRow).payload.size := owner.size
        records(admittedRow).payload.mask := owner.mask
        bound(admittedRow) := false.B
    }

    // Arbitrate one descriptor per cycle. A store leaves queued at selection, so
    // the extra query stage cannot select the same row again on the following edge.
    val queuedMask = VecInit((0 until rows).map(r => state(r) === queued &&
        !ownerCleared(r) && records(r).epoch === io.precheck.epoch)).asUInt
    val storeRow = PriorityEncoder(queuedMask)
    val storeOffer = mayQuery && queuedMask.orR
    val loadOffer = mayQuery && io.loadCandidate.valid
    val preferStore = RegInit(false.B)
    val storeGrant = storeOffer && (!loadOffer || preferStore)
    val loadGrant = loadOffer && !storeGrant
    when(storeGrant || loadGrant) { preferStore := loadGrant }
    val selected = WireDefault(0.U.asTypeOf(new MemoryAddressProof(p)))
    selected.token := Mux(storeGrant, records(storeRow).token, io.loadCandidate.bits.token)
    selected.epoch := io.precheck.epoch
    selected.payload.address := Mux(storeGrant, records(storeRow).payload.address, io.loadCandidate.bits.address)
    selected.payload.size := Mux(storeGrant, records(storeRow).payload.size, io.loadCandidate.bits.size)
    selected.payload.write := storeGrant
    selected.payload.mask := Mux(storeGrant, records(storeRow).payload.mask,
        AlignedMemoryDisjoint.lanes(io.loadCandidate.bits.address, io.loadCandidate.bits.size))
    val queryValid = Wire(Bool())
    val queryStore = Wire(Bool())
    val queryRow = Wire(UInt(rowBits.W))
    val query = Wire(new MemoryAddressProof(p))
    if (registerQuery) {
        val selectedValid = RegInit(false.B)
        val selectedStore = RegInit(false.B)
        val selectedRow = Reg(UInt(rowBits.W))
        val descriptor = Reg(new MemoryAddressProof(p))
        if (rows == 3) {
            when(selectedValid && selectedStore) {
                assert(selectedRow < rows.U, "selected store row encoding3 is not an owner")
            }
        }
        selectedValid := (storeGrant || loadGrant) &&
            !io.clearOwners(selected.token.index) && !consumed(selected)
        when(storeGrant || loadGrant) {
            selectedStore := storeGrant
            selectedRow := storeRow
            descriptor := selected
        }
        // A granted hit-only peek drains even when admission pauses. Clear/consume
        // must not enter request.valid or its payload: they invalidate the result,
        // after the side-effect-free translation lookup. Context cancellation is
        // separate and also frees every unbound inflight row.
        if (rows == 3) {
            queryValid := selectedValid && epochStable && !io.flushQueries &&
                descriptor.epoch === io.precheck.epoch && (!selectedStore || selectedRow < rows.U)
        } else {
            queryValid := selectedValid && epochStable && !io.flushQueries &&
                descriptor.epoch === io.precheck.epoch
        }
        queryStore := selectedStore
        queryRow := selectedRow
        query := descriptor
    } else {
        queryValid := storeGrant || loadGrant
        queryStore := storeGrant
        queryRow := storeRow
        query := selected
    }
    if (rows == 3) {
        when(queryValid && queryStore) {
            assert(queryRow < rows.U, "query store row encoding3 is not an owner")
        }
    }
    io.precheck.request.valid := queryValid
    io.precheck.request.bits.address := query.payload.address
    io.precheck.request.bits.size := query.payload.size
    io.precheck.request.bits.write := queryStore
    val translatedValid = RegInit(false.B)
    val translatedStore = RegInit(false.B)
    val translatedRow = Reg(UInt(rowBits.W))
    val translated = Reg(new MemoryAddressProof(p))
    val translatedNormal = RegInit(false.B)
    if (rows == 3) {
        when(translatedValid && translatedStore) {
            assert(translatedRow < rows.U, "translated store row encoding3 is not an owner")
        }
    }
    // Three-row unused encoding is clamped only for raw array access; the original
    // index-valid guard independently denies authority. One/two-row elaborations are unchanged.
    val safeQueryRow = if (rows == 3) Mux(queryRow < rows.U, queryRow, 0.U) else queryRow
    val safeTranslatedRow = if (rows == 3)
        Mux(translatedRow < rows.U, translatedRow, 0.U) else translatedRow
    val queryOwnerLive = if (rows == 3)
        !io.clearOwners(query.token.index) && !consumed(query) &&
            (!queryStore || (queryRow < rows.U && state(safeQueryRow) === inflight &&
                sameDescriptor(records(safeQueryRow), query) && rowOwnerMatches(safeQueryRow)))
        else !io.clearOwners(query.token.index) && !consumed(query) &&
            (!queryStore || (state(queryRow) === inflight && sameDescriptor(records(queryRow), query) &&
                rowOwnerMatches(queryRow)))
    translatedValid := io.precheck.request.valid && (if (registerQuery) queryOwnerLive else true.B)
    when(io.precheck.request.valid) {
        translatedStore := queryStore
        translatedRow := queryRow
        translated := query
        translated.payload.physicalAddress := Mux(io.precheck.response.valid,
            io.precheck.response.bits.physicalAddress, 0.U)
        translatedNormal := io.precheck.response.valid && io.precheck.response.bits.pbmt === 0.U &&
            io.precheck.response.bits.epoch === io.precheck.epoch
    }
    when(storeGrant) { state(storeRow) := inflight }
    val checkedSize = Mux(translatedValid, translated.payload.size(1, 0), 0.U)
    val alignmentMask = MuxLookup(checkedSize, 7.U(3.W))(Seq(0.U -> 0.U, 1.U -> 1.U, 2.U -> 3.U))
    val pmp = Module(new PmpChecker(p.pmpEntries, naturalAlignedAccess = true, sharedAlignedBounds = true))
    pmp.io.state := io.pmpState
    pmp.io.privilege := io.privilege
    pmp.io.address := Cat(translated.payload.physicalAddress(63, 3),
        translated.payload.physicalAddress(2, 0) & ~alignmentMask)
    pmp.io.size := checkedSize
    pmp.io.access := Mux(translatedStore, PmpAccess.write, PmpAccess.read)
    val shape = translated.payload.size <= 3.U &&
        AlignedMemoryDisjoint.aligned(translated.payload.address, translated.payload.size) &&
        AlignedMemoryDisjoint.aligned(translated.payload.physicalAddress, translated.payload.size) &&
        translated.payload.address(11, 0) === translated.payload.physicalAddress(11, 0) &&
        translated.payload.mask === AlignedMemoryDisjoint.lanes(translated.payload.physicalAddress, translated.payload.size) &&
        SpeculativeRamRange.contains(p, translated.payload.physicalAddress, translated.payload.size)
    val freshResult = translatedValid && epochStable && translated.epoch === io.precheck.epoch && !io.flushQueries
    val allowed = translatedNormal && !pmp.io.denied && shape
    // Clear/consume may free and later reuse a row while an old descriptor drains.
    // Only the same still-live inflight owner has the immutable-record invariant;
    // the functional result guard independently checks its complete descriptor.
    val translatedRowLive = if (rows == 3)
        translatedRow < rows.U && state(safeTranslatedRow) === inflight &&
            records(safeTranslatedRow).token.asUInt === translated.token.asUInt &&
            records(safeTranslatedRow).epoch === translated.epoch && rowOwnerMatches(safeTranslatedRow) &&
            !io.clearOwners(translated.token.index) && !consumed(translated)
        else state(translatedRow) === inflight &&
            records(translatedRow).token.asUInt === translated.token.asUInt &&
            records(translatedRow).epoch === translated.epoch && rowOwnerMatches(translatedRow) &&
            !io.clearOwners(translated.token.index) && !consumed(translated)
    when(translatedValid && translatedStore && translatedRowLive) {
        assert(sameDescriptor(records(safeTranslatedRow), translated),
            "a granted pending-store row preserves its exact owner descriptor through translation")
    }
    val storeResult = freshResult && translatedStore && translatedRowLive &&
        sameDescriptor(records(safeTranslatedRow), translated)
    when(storeResult) {
        state(safeTranslatedRow) := Mux(allowed, proved, free)
        when(allowed) { records(safeTranslatedRow) := translated }
    }
    val loadValid = RegInit(false.B)
    val load = Reg(new VirtualRamLoadCertificate(p))
    // A store grant/bubble does not erase a matching load proof. Only another
    // load result or explicit context/owner invalidation replaces this record.
    when(freshResult && !translatedStore && !io.clearOwners(translated.token.index) && !consumed(translated)) {
        loadValid := true.B
        load.token := translated.token
        load.address := translated.payload.address
        load.size := translated.payload.size(1, 0)
        load.physicalAddress := translated.payload.physicalAddress
        load.epoch := translated.epoch
        load.allowed := allowed
    }
    when(cancelQueries || (loadValid && (load.epoch =/= io.precheck.epoch ||
        io.clearOwners(load.token.index) || (io.consume.valid && io.consume.bits.asUInt === load.token.asUInt)))) {
        loadValid := false.B
    }
    val loadPreparedIntrinsicValid = loadValid && epochStable && load.epoch === io.precheck.epoch
    io.loadPrepared.valid := loadPreparedIntrinsicValid && !io.flushQueries
    io.loadPreparedCandidateValid.foreach(_ := loadPreparedIntrinsicValid)
    io.loadPrepared.bits := load
    when(cancelQueries) { translatedValid := false.B }
    for (r <- 0 until rows) {
        io.proofs(r).valid := liveRows(r)
        io.proofs(r).bits := records(r)
        when(io.bind(r)) {
            assert(!io.flushQueries && liveRows(r) && !ownerCleared(r),
                "an early load can bind only a live exact pending-store certificate")
            bound(r) := true.B
        }
        val ownerGone = ownerCleared(r)
        val epochGone = records(r).epoch =/= io.precheck.epoch
        when(state(r) =/= free && bound(r) && !ownerGone) {
            assert(!epochGone, "a surviving bound store cannot cross an authorization epoch")
        }
        // Same-edge owner clear/consume wins over result capture and binding.
        when(state(r) =/= free && (ownerGone || (!bound(r) &&
            (epochGone || cancelQueries || (evict && victim === r.U))))) {
            state(r) := free
            bound(r) := false.B
        }
        when(bound(r)) { assert(state(r) === proved) }
    }
    io.bound := bound.asUInt
    io.reservedCount := PopCount(state.map(s => s === queued || s === inflight))
    io.provedCount := PopCount(state.map(_ === proved))
}

/** Bounded early-load responsibilities. Reserve is the first committed offer;
  * consume is actual LSU capture. Reserved and active entries share one capacity.
  * Only pre-edge free entries admit new owners; active entries return after their
  * exact full token disappears from every busy LSU slot after completion/discard.
  */
class PendingStoreEarlyLoadCredit(p: OooParams) extends Module {
    require(p.pendingVirtualStoreProof)
    private val capacity = p.pendingStoreEarlyLoadCredits
    val io = IO(new Bundle {
        val reserve = Input(Valid(new RobToken(p)))
        val consume = Input(Valid(new RobToken(p)))
        val cancelReservation = Input(Valid(new RobToken(p)))
        val liveOwners = Input(Vec(p.memoryEntries, Valid(new RobToken(p))))
        val available = Output(Bool())
        val reserved = Output(Vec(capacity, Bool()))
        val active = Output(Vec(capacity, Bool()))
        val owner = Output(Vec(capacity, new RobToken(p)))
    })
    val free :: reserved :: active :: Nil = Enum(3)
    val state = RegInit(VecInit(Seq.fill(capacity)(free)))
    val owner = Reg(Vec(capacity, new RobToken(p)))
    val freeEntries = VecInit(state.map(_ === free))
    // Reclaim affects only next state, never this admission/READY path.
    io.available := freeEntries.asUInt.orR
    val reserveEntry = PriorityEncoderOH(freeEntries.asUInt)
    val consumeMatches = Wire(Vec(capacity, Bool()))
    val cancelMatches = Wire(Vec(capacity, Bool()))
    for (entry <- 0 until capacity) {
        io.reserved(entry) := state(entry) === reserved
        io.active(entry) := state(entry) === active
        io.owner(entry) := owner(entry)
        val live = io.liveOwners.map(o =>
            o.valid && o.bits.asUInt === owner(entry).asUInt).reduce(_ || _)
        val reserveHere = io.reserve.valid && reserveEntry(entry)
        consumeMatches(entry) := (state(entry) === reserved &&
            owner(entry).asUInt === io.consume.bits.asUInt) ||
            (reserveHere && io.reserve.bits.asUInt === io.consume.bits.asUInt)
        cancelMatches(entry) := state(entry) === reserved &&
            owner(entry).asUInt === io.cancelReservation.bits.asUInt
        when(state(entry) === active && !live) { state(entry) := free }
        when(reserveHere) {
            state(entry) := reserved
            owner(entry) := io.reserve.bits
        }
        when(io.consume.valid && consumeMatches(entry)) { state(entry) := active }
        when(io.cancelReservation.valid && cancelMatches(entry)) { state(entry) := free }
        when(io.reserve.valid && state(entry) =/= free) {
            assert(owner(entry).asUInt =/= io.reserve.bits.asUInt,
                "a full token cannot reserve a second early-load responsibility")
        }
        for (other <- 0 until entry) {
            when(state(entry) =/= free && state(other) =/= free) {
                assert(owner(entry).asUInt =/= owner(other).asUInt,
                    "nonfree early-load responsibilities have distinct full tokens")
            }
        }
    }
    when(io.reserve.valid) {
        assert(io.available, "early-load reserve requires a pre-edge free entry, with no same-edge drain reuse")
    }
    when(io.consume.valid) {
        assert(PopCount(consumeMatches) === 1.U,
            "early-load consumption requires exactly one reserved or freshly reserved full token")
    }
    when(io.cancelReservation.valid) {
        assert(!io.consume.valid && PopCount(cancelMatches) === 1.U,
            "only an unconsumed exact offer may cancel its reservation")
    }
    for (slot <- 0 until p.memoryEntries; other <- 0 until slot) {
        when(io.liveOwners(slot).valid && io.liveOwners(other).valid) {
            assert(io.liveOwners(slot).bits.asUInt =/= io.liveOwners(other).bits.asUInt,
                "an accepted full token owns at most one live LSU slot")
        }
    }
}
