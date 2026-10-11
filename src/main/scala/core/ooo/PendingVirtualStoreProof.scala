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

/** One/two retained write certificates, sharing one hit-only query and one registered PMP
  * checker with the original load preparation. Target: one query/cycle, load/store fairness
  * within two available query cycles, two query-to-proof register boundaries. Proof storage
  * grants no memory ownership; bound rows survive until exact actual-store capture or kill.
  */
class PendingVirtualStoreProof(p: OooParams) extends Module {
    require(p.pendingVirtualStoreProof)
    private val rows = p.pendingVirtualStoreProofSlots
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
    def ownerCleared(proof: MemoryAddressProof): Bool = io.clearOwners(proof.token.index) ||
        !ownerMatches(proof) || consumed(proof)
    val epochStable = io.precheck.stable
    val cancelQueries = io.flushQueries || !epochStable
    val liveRows = VecInit((0 until rows).map(r => state(r) === proved && ownerMatches(records(r)) &&
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
    // Eviction is a separate edge. Never replace a queued, inflight, or bound proof.
    val evictable = (0 until rows).map(r => state(r) === proved && !bound(r) &&
        (records(r).token.index - io.head) > (admitIndex - io.head))
    val victim = (0 until rows).map(r => (evictable(r), r.U(rowBits.W), records(r).token.index - io.head))
        .reduce { (a, b) => (a._1 || b._1,
            Mux(a._1 && (!b._1 || a._3 > b._3), a._2, b._2),
            Mux(a._1 && (!b._1 || a._3 > b._3), a._3, b._3)) }._2
    val evict = mayQuery && queryMask.orR && !empty.orR && evictable.reduce(_ || _)
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

    // Same-cycle hit-only responses belong to exactly this grant. The registered
    // descriptor carries the access kind through the shared physical PMP stage.
    val queuedMask = VecInit((0 until rows).map(r => state(r) === queued &&
        !ownerCleared(records(r)) && records(r).epoch === io.precheck.epoch)).asUInt
    val storeRow = PriorityEncoder(queuedMask)
    val storeOffer = mayQuery && queuedMask.orR
    val loadOffer = mayQuery && io.loadCandidate.valid
    val preferStore = RegInit(false.B)
    val storeGrant = storeOffer && (!loadOffer || preferStore)
    val loadGrant = loadOffer && !storeGrant
    when(storeGrant || loadGrant) { preferStore := loadGrant }
    io.precheck.request.valid := storeGrant || loadGrant
    io.precheck.request.bits.address := Mux(storeGrant,
        records(storeRow).payload.address, io.loadCandidate.bits.address)
    io.precheck.request.bits.size := Mux(storeGrant,
        records(storeRow).payload.size, io.loadCandidate.bits.size)
    io.precheck.request.bits.write := storeGrant
    val translatedValid = RegInit(false.B)
    val translatedStore = RegInit(false.B)
    val translatedRow = Reg(UInt(rowBits.W))
    val translated = Reg(new MemoryAddressProof(p))
    val translatedNormal = RegInit(false.B)
    translatedValid := io.precheck.request.valid
    when(io.precheck.request.valid) {
        translatedStore := storeGrant
        translatedRow := storeRow
        translated.token := Mux(storeGrant, records(storeRow).token, io.loadCandidate.bits.token)
        translated.epoch := io.precheck.epoch
        translated.payload.address := io.precheck.request.bits.address
        translated.payload.size := io.precheck.request.bits.size
        translated.payload.write := storeGrant
        translated.payload.mask := Mux(storeGrant, records(storeRow).payload.mask,
            AlignedMemoryDisjoint.lanes(io.loadCandidate.bits.address, io.loadCandidate.bits.size))
        translated.payload.physicalAddress := Mux(io.precheck.response.valid,
            io.precheck.response.bits.physicalAddress, 0.U)
        translatedNormal := io.precheck.response.valid && io.precheck.response.bits.pbmt === 0.U &&
            io.precheck.response.bits.epoch === io.precheck.epoch
    }
    when(storeGrant) { state(storeRow) := inflight }
    val checkedSize = Mux(translatedValid, translated.payload.size(1, 0), 0.U)
    val alignmentMask = MuxLookup(checkedSize, 7.U(3.W))(Seq(0.U -> 0.U, 1.U -> 1.U, 2.U -> 3.U))
    val pmp = Module(new PmpChecker(p.pmpEntries, naturalAlignedAccess = true))
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
    val storeResult = freshResult && translatedStore && state(translatedRow) === inflight &&
        records(translatedRow).token.asUInt === translated.token.asUInt &&
        records(translatedRow).epoch === translated.epoch && ownerMatches(translated) && !ownerCleared(translated)
    when(storeResult) {
        state(translatedRow) := Mux(allowed, proved, free)
        when(allowed) { records(translatedRow) := translated }
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
    io.loadPrepared.valid := loadValid && epochStable && load.epoch === io.precheck.epoch &&
        !io.flushQueries
    io.loadPrepared.bits := load
    when(cancelQueries) { translatedValid := false.B }
    for (r <- 0 until rows) {
        io.proofs(r).valid := liveRows(r)
        io.proofs(r).bits := records(r)
        when(io.bind(r)) {
            assert(!io.flushQueries && liveRows(r) && !ownerCleared(records(r)),
                "an early load can bind only a live exact pending-store certificate")
            bound(r) := true.B
        }
        val ownerGone = ownerCleared(records(r))
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

/** One early-load credit. Reserve is the first committed offer; consume is actual
  * LSU capture. A reserved credit cannot be returned by the absence of an LSU owner.
  * Active credit returns only after the original full-token completion/discard drain.
  */
class PendingStoreEarlyLoadCredit(p: OooParams) extends Module {
    require(p.pendingVirtualStoreProof)
    val io = IO(new Bundle {
        val reserve = Input(Valid(new RobToken(p)))
        val consume = Input(Valid(new RobToken(p)))
        val cancelReservation = Input(Valid(new RobToken(p)))
        val liveOwners = Input(Vec(p.memoryEntries, Valid(new RobToken(p))))
        val available = Output(Bool())
        val reserved = Output(Bool())
        val active = Output(Bool())
        val owner = Output(new RobToken(p))
    })
    val free :: reserved :: active :: Nil = Enum(3)
    val state = RegInit(free)
    val owner = Reg(new RobToken(p))
    io.available := state === free
    io.reserved := state === reserved
    io.active := state === active
    io.owner := owner
    val live = io.liveOwners.map(o => o.valid && o.bits.asUInt === owner.asUInt).reduce(_ || _)
    when(state === active && !live) { state := free }
    when(io.reserve.valid) {
        assert(state === free, "there is exactly one early-load credit, with no same-edge drain reuse")
        state := reserved
        owner := io.reserve.bits
    }
    when(io.consume.valid) {
        assert((state === reserved && owner.asUInt === io.consume.bits.asUInt) ||
            (state === free && io.reserve.valid && io.reserve.bits.asUInt === io.consume.bits.asUInt),
            "early-load consumption requires its exact reserved full token")
        state := active
    }
    when(io.cancelReservation.valid) {
        assert(!io.consume.valid && state === reserved && owner.asUInt === io.cancelReservation.bits.asUInt,
            "only an unconsumed exact offer may cancel its reservation")
        state := free
    }
}
