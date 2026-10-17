package soc.core.ooo

import chisel3._
import chisel3.util._

/** Immutable authority for one pending ordinary memory owner. Not a completion or memory request. */
class MemoryProofPayload extends Bundle {
    val address = UInt(64.W)
    val physicalAddress = UInt(64.W)
    val write = Bool()
    val size = UInt(3.W)
    val mask = UInt(8.W)
}
class MemoryAddressProof(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    val epoch = UInt(32.W)
    val payload = new MemoryProofPayload
}
class MemoryProofQuery(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    val address = UInt(64.W)
    val write = Bool()
    val size = UInt(3.W)
}
class MemoryProofLine(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    val line = UInt(58.W)
}

/** Sixteen credits INCLUDE the three locally owned query pipeline positions. One logical
  * payload write and one arbitrated payload read per cycle. Full owner metadata is independent
  * from the ROB; the ROB-index directory is only a narrow inverse mapping, never authority.
  * Target: II=1 positive preparation, 16 row scan + setup/validation <=20 cycles without preemption.
  */
class MemoryProofFrontier(p: OooParams) extends Module {
    require(p.memoryProofFrontier && p.memoryProofRows == 16)
    private val rows = 16
    private val rowBits = 4
    val io = IO(new Bundle {
        val head = Input(UInt(p.robBits.W))
        val pending = Input(UInt(p.robEntries.W))
        val memoryLive = Input(UInt(p.robEntries.W))
        val ordinary = Input(UInt(p.robEntries.W))
        val stores = Input(UInt(p.robEntries.W))
        val systems = Input(UInt(p.robEntries.W))
        val canonicalLoads = Input(UInt(p.robEntries.W))
        val canonicalStores = Input(UInt(p.robEntries.W))
        val checkedStore = Input(Valid(new CanonicalStoreCertificate(p)))
        val clearOwners = Input(UInt(p.robEntries.W)) // kill, retire and allocate; same-edge clear wins
        val pause = Input(Bool()) // interrupts/system drains: keep existing bound tuples
        val flushQueries = Input(Bool()) // cancellation kills ALL local valids and reservations together
        val queryEligible = Input(UInt(p.robEntries.W))
        val queryOwner = Output(Valid(UInt(p.robBits.W)))
        val query = Input(new MemoryProofQuery(p)) // selected registered-ready AGU, no rs2 requirement
        val resultIndex = Output(UInt(p.robBits.W))
        val resultToken = Input(new RobToken(p)) // exactly one selected live ROB metadata read
        val precheck = new VirtualLoadPrecheckPort
        val pmpState = Input(new PmpState)
        val privilege = Input(UInt(2.W))
        val selected = Input(Valid(new RobToken(p)))
        val selectedProof = Output(Valid(new MemoryAddressProof(p)))
        val selectedBound = Output(Bool())
        val frontier = Output(Valid(new MemoryAddressProof(p)))
        val frontierAccepted = Input(Bool())
        val consume = Input(Valid(new RobToken(p))) // every actual memory start, all routes
        val liveLines = Input(Vec(p.memoryEntries, Valid(new MemoryProofLine(p))))
        val pendingProof = Output(UInt(p.robEntries.W))
        val reservedCount = Output(UInt(5.W))
        val allowedCount = Output(UInt(5.W))
        val boundCount = Output(UInt(5.W))
    })
    val free :: reserved :: allowed :: Nil = Enum(3)
    val state = RegInit(VecInit(Seq.fill(rows)(free)))
    val tokens = Reg(Vec(rows, new RobToken(p)))
    val epochs = Reg(Vec(rows, UInt(32.W)))
    val bound = RegInit(VecInit(Seq.fill(rows)(false.B)))
    val payload = Mem(rows, new MemoryProofPayload)
    val directory = Reg(Vec(p.robEntries, UInt(rowBits.W)))
    val present = RegInit(0.U(p.robEntries.W))
    val positive = RegInit(0.U(p.robEntries.W))
    val queryAttempted = RegInit(0.U(p.robEntries.W))
    val scanAttempted = RegInit(0.U(p.robEntries.W))
    def oldest(mask: UInt): UInt = {
        val after = mask & VecInit((0 until p.robEntries).map(i => i.U >= io.head)).asUInt
        OHToUInt(PriorityEncoderOH(Mux(after.orR, after, mask)))
    }
    def ownerBit(index: UInt): UInt = UIntToOH(index, p.robEntries)
    def live(row: UInt): Bool = state(row) === allowed && io.pending(tokens(row).index) &&
        io.ordinary(tokens(row).index) && present(tokens(row).index) &&
        directory(tokens(row).index) === row && epochs(row) === io.precheck.epoch
    val queryMask = io.queryEligible & io.pending & io.ordinary & ~present & ~queryAttempted & ~io.clearOwners
    val queryIndex = oldest(queryMask)
    val freeMask = VecInit(state.map(_ === free)).asUInt
    val queryMayRun = io.precheck.stable && !io.pause && !io.flushQueries
    val evictable = VecInit((0 until rows).map(r => state(r) === allowed && !bound(r) &&
        (tokens(r).index - io.head) > (queryIndex - io.head)))
    val victim = (0 until rows).map(r => (evictable(r), r.U(rowBits.W), tokens(r).index - io.head))
        .reduce { (a, b) => (a._1 || b._1,
            Mux(a._1 && (!b._1 || a._3 > b._3), a._2, b._2),
            Mux(a._1 && (!b._1 || a._3 > b._3), a._3, b._3)) }._2
    val evict = queryMayRun && queryMask.orR && !freeMask.orR && evictable.asUInt.orR
    val admission = queryMayRun && queryMask.orR && freeMask.orR
    val admittedRow = PriorityEncoder(freeMask)
    io.queryOwner.valid := admission
    io.queryOwner.bits := queryIndex

    val addressValid = RegInit(false.B)
    val addressProof = Reg(new MemoryAddressProof(p))
    val addressRow = Reg(UInt(rowBits.W))
    val translatedValid = RegInit(false.B)
    val translatedProof = Reg(new MemoryAddressProof(p))
    val translatedRow = Reg(UInt(rowBits.W))
    val translatedNormal = Reg(Bool())
    val resultValid = RegInit(false.B)
    val resultProof = Reg(new MemoryAddressProof(p))
    val resultRow = Reg(UInt(rowBits.W))
    val resultAllowed = Reg(Bool())
    val cancelQueries = io.flushQueries || !io.precheck.stable
    def cancelled(proof: MemoryAddressProof): Bool = io.clearOwners(proof.token.index) ||
        !io.pending(proof.token.index) || proof.epoch =/= io.precheck.epoch || cancelQueries ||
        (io.consume.valid && io.consume.bits.asUInt === proof.token.asUInt)
    addressValid := admission
    when(admission) {
        assert(io.query.token.index === queryIndex)
        addressRow := admittedRow
        addressProof.token := io.query.token
        addressProof.epoch := io.precheck.epoch
        addressProof.payload.address := io.query.address
        addressProof.payload.physicalAddress := 0.U
        addressProof.payload.write := io.query.write
        addressProof.payload.size := io.query.size
        addressProof.payload.mask := AlignedMemoryDisjoint.lanes(io.query.address, io.query.size)
    }
    io.precheck.request.valid := addressValid && !cancelled(addressProof)
    io.precheck.request.bits.address := addressProof.payload.address
    io.precheck.request.bits.size := addressProof.payload.size
    io.precheck.request.bits.write := addressProof.payload.write
    translatedValid := io.precheck.request.valid
    when(io.precheck.request.valid) {
        translatedRow := addressRow
        translatedProof := addressProof
        translatedProof.payload.physicalAddress := Mux(io.precheck.response.valid,
            io.precheck.response.bits.physicalAddress, 0.U)
        translatedNormal := io.precheck.response.valid && io.precheck.response.bits.pbmt === 0.U &&
            io.precheck.response.bits.epoch === addressProof.epoch
    }
    val pmp = Module(new PmpChecker(p.pmpEntries, naturalAlignedAccess = true))
    pmp.io.state := io.pmpState
    pmp.io.privilege := io.privilege
    val checkedSize = Mux(translatedValid, translatedProof.payload.size(1, 0), 0.U)
    val alignmentMask = MuxLookup(checkedSize, 7.U(3.W))(Seq(0.U -> 0.U, 1.U -> 1.U, 2.U -> 3.U))
    pmp.io.address := Cat(translatedProof.payload.physicalAddress(63, 3),
        translatedProof.payload.physicalAddress(2, 0) & ~alignmentMask)
    pmp.io.size := checkedSize
    pmp.io.access := Mux(translatedProof.payload.write, PmpAccess.write, PmpAccess.read)
    resultValid := translatedValid && !cancelled(translatedProof)
    when(translatedValid) {
        resultRow := translatedRow
        resultProof := translatedProof
        val v = translatedProof.payload
        resultAllowed := translatedNormal && v.size <= 3.U && !pmp.io.denied &&
            AlignedMemoryDisjoint.aligned(v.address, v.size) &&
            AlignedMemoryDisjoint.aligned(v.physicalAddress, v.size) &&
            v.address(11, 0) === v.physicalAddress(11, 0) &&
            SpeculativeRamRange.contains(p, v.physicalAddress, v.size) &&
            v.mask === AlignedMemoryDisjoint.lanes(v.physicalAddress, v.size)
    }
    when(cancelQueries) { addressValid := false.B; translatedValid := false.B; resultValid := false.B }
    io.resultIndex := Mux(resultValid, resultProof.token.index, 0.U)
    val returningReservation = resultValid && state(resultRow) === reserved &&
        tokens(resultRow).asUInt === resultProof.token.asUInt && epochs(resultRow) === resultProof.epoch
    val resultMatches = returningReservation && !cancelled(resultProof) &&
        io.resultToken.asUInt === resultProof.token.asUInt && io.ordinary(resultProof.token.index) &&
        io.stores(resultProof.token.index) === resultProof.payload.write
    val positiveResult = resultMatches && resultAllowed

    // A consumed row is unavailable to new admission until a subsequent edge. No same-edge reuse.
    val consumeRows = VecInit((0 until rows).map(r => state(r) =/= free && io.consume.valid &&
        tokens(r).asUInt === io.consume.bits.asUInt))
    val invalidRows = VecInit((0 until rows).map { r =>
        state(r) =/= free && (io.clearOwners(tokens(r).index) || !io.pending(tokens(r).index) ||
            epochs(r) =/= io.precheck.epoch || (state(r) === reserved && cancelQueries) ||
            (evict && victim === r.U))
    })
    val failedRows = VecInit((0 until rows).map(r => returningReservation && !positiveResult && resultRow === r.U))
    val removedRows = invalidRows.asUInt | consumeRows.asUInt | failedRows.asUInt
    val removedOwners = (0 until rows).map(r => Mux(removedRows(r), ownerBit(tokens(r).index), 0.U)).reduce(_ | _)
    val admittedOwner = Mux(admission, ownerBit(queryIndex), 0.U)
    val resultOwner = Mux(positiveResult, ownerBit(resultProof.token.index), 0.U)
    present := ((present | admittedOwner) & ~removedOwners) & ~io.clearOwners
    positive := ((positive | resultOwner) & ~removedOwners) & ~io.clearOwners
    when(admission) {
        state(admittedRow) := reserved
        tokens(admittedRow) := io.query.token
        epochs(admittedRow) := io.precheck.epoch
        bound(admittedRow) := false.B
        directory(queryIndex) := admittedRow
    }
    when(positiveResult && !removedRows(resultRow)) {
        payload.write(resultRow, resultProof.payload)
        state(resultRow) := allowed
    }
    val queryRemaining = io.queryEligible & io.pending & io.ordinary & ~present
    queryAttempted := Mux(!(queryRemaining & ~queryAttempted).orR, 0.U, queryAttempted | admittedOwner) & ~io.clearOwners

    // One payload read. Head/original selected owner has priority and caches the exact row identity.
    val selectedRow = directory(Mux(io.selected.valid, io.selected.bits.index, 0.U))
    val cachedValid = RegInit(false.B)
    val cachedRow = Reg(UInt(rowBits.W))
    val cached = Reg(new MemoryAddressProof(p))
    val selectedMatches = cachedValid && io.selected.valid &&
        cached.token.asUInt === io.selected.bits.asUInt && live(cachedRow) &&
        tokens(cachedRow).asUInt === cached.token.asUInt && !invalidRows(cachedRow)
    io.selectedProof.valid := selectedMatches && io.precheck.stable
    io.selectedProof.bits := cached
    io.selectedBound := io.selected.valid && present(io.selected.bits.index) &&
        state(selectedRow) === allowed && bound(selectedRow) &&
        tokens(selectedRow).asUInt === io.selected.bits.asUInt
    val selectedRead = io.selected.valid && positive(io.selected.bits.index) && live(selectedRow) &&
        tokens(selectedRow).asUInt === io.selected.bits.asUInt && !selectedMatches && !invalidRows(selectedRow)
    when(!selectedMatches || removedRows(cachedRow)) { cachedValid := false.B }

    val idle :: fetch :: scan :: ready :: Nil = Enum(4)
    val scanState = RegInit(idle)
    val candidateRow = Reg(UInt(rowBits.W))
    val candidate = Reg(new MemoryAddressProof(p))
    val snapshotLive = RegInit(false.B)
    val cursor = RegInit(0.U(rowBits.W))
    val covered = RegInit(0.U(p.robEntries.W))
    val relied = RegInit(0.U(rows.W))
    val candidateMask = positive & io.pending & io.ordinary & ~io.stores & ~scanAttempted & ~io.clearOwners
    val candidateIndex = oldest(candidateMask)
    val scanRead = scanState === scan
    val candidateRead = scanState === fetch
    val readRow = Mux(selectedRead, selectedRow, Mux(candidateRead, candidateRow, cursor))
    val readPayload = payload(readRow) // sole logical payload read
    val readProof = Wire(new MemoryAddressProof(p))
    readProof.token := tokens(readRow)
    readProof.epoch := epochs(readRow)
    readProof.payload := readPayload
    when(selectedRead) { cached := readProof; cachedRow := readRow; cachedValid := true.B }
    when(scanState === idle && candidateMask.orR && queryMayRun) {
        candidateRow := directory(candidateIndex)
        scanState := fetch
        snapshotLive := true.B
        scanAttempted := scanAttempted | ownerBit(candidateIndex)
    }
    val comparedAddress = Mux(candidateRead, readPayload.physicalAddress, candidate.payload.physicalAddress)
    val knownSetConflict = io.liveLines.map(l => l.valid &&
        l.bits.line(log2Ceil(p.memoryProofCacheSets) - 1, 0) ===
            comparedAddress(6 + log2Ceil(p.memoryProofCacheSets) - 1, 6)).reduce(_ || _)
    when(candidateRead && !selectedRead) {
        candidate := readProof
        covered := 0.U
        relied := 0.U
        cursor := 0.U
        scanState := Mux(live(candidateRow) && !readPayload.write && !knownSetConflict, scan, idle)
    }
    when(scanRead && !selectedRead) {
        val older = (tokens(cursor).index - io.head) < (candidate.token.index - io.head)
        val disjoint = AlignedMemoryDisjoint.withLanes(candidate.payload.physicalAddress, true.B,
            candidate.payload.mask, readPayload.physicalAddress(63, 3), readPayload.mask)
        val useful = live(cursor) && older && !invalidRows(cursor) &&
            readPayload.write === io.stores(tokens(cursor).index) && (!readPayload.write || disjoint)
        when(useful) {
            covered := covered | ownerBit(tokens(cursor).index)
            relied := relied | UIntToOH(cursor, rows)
        }
        when(cursor === (rows - 1).U) { scanState := ready }.otherwise { cursor := cursor + 1.U }
    }
    val olderMask = VecInit((0 until p.robEntries).map(i =>
        (i.U(p.robBits.W) - io.head) < (candidate.token.index - io.head))).asUInt
    val olderMemory = olderMask & io.memoryLive
    val pendingOlder = olderMemory & io.pending
    val startedOlder = olderMemory & ~io.pending
    val checked = io.checkedStore.bits
    val checkedDisjoint = io.checkedStore.valid && AlignedMemoryDisjoint.withLanes(
        candidate.payload.physicalAddress, true.B, candidate.payload.mask, checked.physicalAddress(63, 3), checked.mask)
    val coverage = !(pendingOlder & ~covered).orR && !(olderMemory & ~io.ordinary).orR &&
        !(olderMask & io.systems).orR &&
        !(startedOlder & ~io.stores & ~io.canonicalLoads).orR &&
        !(startedOlder & io.stores & ~io.canonicalStores).orR &&
        (!(startedOlder & io.stores).orR || checkedDisjoint)
    val losesAllowed = VecInit((0 until rows).map(r => state(r) === allowed && invalidRows(r))).asUInt.orR
    io.frontier.valid := scanState === ready && snapshotLive && live(candidateRow) &&
        tokens(candidateRow).asUInt === candidate.token.asUInt && !losesAllowed && !knownSetConflict && coverage && queryMayRun
    io.frontier.bits := candidate
    when(scanState === ready && (!coverage || knownSetConflict)) { scanState := idle }
    when(io.frontierAccepted) {
        assert(io.frontier.valid && io.consume.valid && io.consume.bits.asUInt === candidate.token.asUInt)
        for (r <- 0 until rows) { when(relied(r)) { assert(live(r.U)); bound(r) := true.B } }
        scanState := idle
        snapshotLive := false.B
    }
    when(losesAllowed || io.flushQueries || !io.precheck.stable ||
        (consumeRows.asUInt.orR && !io.frontierAccepted)) {
        snapshotLive := false.B
        scanState := idle
    }
    // Availability changes restart finite rounds; removal invalidation is sticky through READY.
    val oldLineMask = RegNext(VecInit(io.liveLines.map(_.valid)).asUInt, 0.U)
    when(positiveResult || removedRows.orR || io.consume.valid || oldLineMask =/= VecInit(io.liveLines.map(_.valid)).asUInt ||
        !(positive & io.pending & io.ordinary & ~io.stores & ~scanAttempted).orR) { scanAttempted := 0.U }
    for (r <- 0 until rows) {
        when(removedRows(r)) { state(r) := free; bound(r) := false.B }
        when(state(r) =/= free) {
            assert(present(tokens(r).index) && directory(tokens(r).index) === r.U,
                "every proof credit has exactly its inverse ROB owner mapping")
        }
        when(state(r) === allowed && bound(r) && epochs(r) =/= io.precheck.epoch &&
            !io.clearOwners(tokens(r).index)) {
            assert(false.B, "context epoch must not discard a surviving bound pending proof")
        }
        when(consumeRows(r) && bound(r)) { assert(state(r) === allowed) }
    }
    for (i <- 0 until p.robEntries) {
        when(present(i)) { assert(state(directory(i)) =/= free && tokens(directory(i)).index === i.U) }
    }
    io.pendingProof := positive
    io.reservedCount := PopCount(state.map(_ === reserved))
    io.allowedCount := PopCount(state.map(_ === allowed))
    io.boundCount := PopCount((0 until rows).map(r => state(r) === allowed && bound(r)))
    assert(io.reservedCount +& io.allowedCount <= rows.U)
}
