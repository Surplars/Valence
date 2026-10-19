package soc.core.inorder

import soc.core.ooo.{CacheTagConfig, HomeRamRange, ParallelHomeLineMatch}

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLBundle, TLOpcode, TLParams, TLPermissions}
import soc.ip.tilelink.TileLinkLineAcquireEngine

class I1CoherentCacheProfile extends Bundle {
    val emptySlotMiss = Bool()
    val replacementMiss = Bool()
    val readMiss = Bool()
    val writeMiss = Bool()
    val dirtyEviction = Bool()
    val missBlocked = Bool()
    val bypassBlocked = Bool()
    val probeBlocked = Bool()
    val evictionCycle = Bool()
    val refillCycle = Bool()
}

/** Single-client, write-back 64-byte L1. Resident lines own T permission; dirty data reaches
  * the home through ReleaseData on eviction or ProbeAckData on an external access.
  * One or two ways share the same total line capacity and synchronous data banks.
  * Hits retain one-cycle SRAM latency and ordered, backpressured responses; a miss
  * still owns one slot until refill completes. Two-way LRU only changes placement.
  */
class I1CoherentLineCache(
    base: BigInt = BigInt("80010000", 16), bytes: BigInt = 8192, lines: Int = 128,
    params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
    ways: Int = 1, responseEntries: Int = 2, tagConfig: CacheTagConfig = CacheTagConfig.FullWidth,
    controlTimingCuts: Boolean = false, orderedReadOnly: Boolean = false,
    orderedDataAdmission: Boolean = false, trustedReadOnlyCacheability: Boolean = false,
    fetchPredecode: Boolean = false, internalLineGrant: Boolean = false,
    missTurnover: Boolean = false, writebackOverlap: Boolean = false
) extends I1CoherentLineCacheModule(params, trustedReadOnlyCacheability, internalLineGrant) {
    require(!missTurnover || (controlTimingCuts && orderedDataAdmission && ways == 2))
    require(!fetchPredecode || (orderedReadOnly && controlTimingCuts && ways == 2))
    require(!orderedReadOnly || controlTimingCuts)
    require(!orderedDataAdmission || controlTimingCuts)
    require(!trustedReadOnlyCacheability || (controlTimingCuts && orderedReadOnly))
    private val orderedAdmission = orderedReadOnly || orderedDataAdmission
    private val retainedOrderedBypass = controlTimingCuts && orderedAdmission
    private val parallelWayReads = controlTimingCuts && orderedAdmission && ways == 2
    private val parallelOrderedControl = controlTimingCuts && orderedAdmission
    private val retimedOrderedClassify = controlTimingCuts && orderedAdmission && ways == 2
    private val retimedDataCommit = retimedOrderedClassify && orderedDataAdmission
    require(responseEntries >= 2 && responseEntries <= 16 && isPow2(responseEntries))
    require(lines >= 2 && lines <= 512 && isPow2(lines))
    require(Set(1, 2).contains(ways) && lines / ways >= 2)
    require(bytes >= 64 && bytes % 64 == 0 && base % 64 == 0)
    private val indexBits = log2Ceil(lines)
    private val setBits = log2Ceil(lines / ways)
    private val tagGeometry = tagConfig.geometry(base, bytes, 6 + setBits)
    private val Seq(idle, evictCapture, evictSend, evictAck, acquire, fill, missResponse,
        bypassSend, bypassResponse, probeCapture, probeSend, flushScan) =
        (if (parallelOrderedControl) (0 until 12).map(i => (BigInt(1) << i).U(12.W)) else Enum(12))
    private val stateStorage = RegInit(idle)
    private val state = WireDefault(UInt(idle.getWidth.W), stateStorage)
    // Classification can only choose idle/acquire/evictCapture/bypassSend.
    // Other maintenance phases have an already registered owner; never
    // distribute late tag decisions through their BRAM/metadata controls.
    private val maintenanceState = if (retimedOrderedClassify) stateStorage else state
    private def phaseIs(value: UInt, phase: UInt): Bool =
        if (parallelOrderedControl) value(phase.litValue.bitLength - 1) else value === phase
    private def in(phase: UInt): Bool = phaseIs(state, phase)
    private def maintaining(phase: UInt): Bool = phaseIs(maintenanceState, phase)
    if (parallelOrderedControl) when(!reset.asBool) {
        assert(PopCount(stateStorage) === 1.U && PopCount(state) === 1.U,
            "cache phase lost its single existing owner")
    }
    private val legacyNextState = WireDefault(state)
    stateStorage := legacyNextState
    private val valid = RegInit(VecInit(Seq.fill(lines)(false.B)))
    private val dirty = RegInit(VecInit(Seq.fill(lines)(false.B)))
    // One shared lookup set, one asynchronous RAM per physical way. CPU,
    // probe and flush lookups are mutually exclusive; never synthesize three
    // replicated 512-way FF mux trees just to read the same metadata.
    private val tagBanks = Seq.fill(ways)(Mem(lines / ways, UInt(tagGeometry.tagBits.W)))
    // firtool cannot attach AttributeAnnotation to memory ops. The physical
    // exporter binds ram_style to the real emitted Memory array, hash-checked.
    private val replacement = if (ways == 2)
        Some(RegInit(VecInit(Seq.fill(lines / ways)(false.B)))) else None
    private val data = if (!parallelWayReads)
        Seq.fill(8)(SyncReadMem(lines, Vec(8, UInt(8.W)))) else Seq.empty
    // Same logical line/way capacity. Split physical SRAM by way so both
    // candidate rows can be read BEFORE tag qualification; choose using the
    // existing retained hit/probe/flush owner AFTER the synchronous RAM edge.
    // This trades BRAM packing for a shorter path, not a longer hit pipeline.
    private val dataWays = if (parallelWayReads)
        Seq.fill(8)(Seq.fill(2)(SyncReadMem(lines / 2, Vec(8, UInt(8.W)), SyncReadMem.ReadFirst))) else Seq.empty
    // Refill-time format metadata: two bits/halfword in RAM, not a new line owner.
    private val fetchClassBanks = if (fetchPredecode)
        Seq.fill(ways)(Mem(lines / ways, Vec(8, UInt(8.W)))) else Seq.empty
    private val pending = Reg(new I1DataRequest)
    private val pendingIndexStorage = Reg(UInt(indexBits.W))
    private val pendingIndex = WireDefault(pendingIndexStorage)
    private val maintenanceIndex = if (retimedOrderedClassify) pendingIndexStorage else pendingIndex
    private val pendingBypass = Reg(Bool())
    private val missResult = Reg(new I1DataResponse)
    private val victimAddress = Reg(UInt(64.W))
    private val victimTags = if (controlTimingCuts)
        Some(Reg(Vec(ways, UInt(tagGeometry.tagBits.W)))) else None
    // Reuse pending/victimTags and the existing SRAM return cycle. There is
    // still ONE accepted owner. Only valid-way bits and a classification
    // marker are new; no line, queue entry or hit-latency edge is added.
    private val classifyPending = if (retimedOrderedClassify) Some(RegInit(false.B)) else None
    private val classifyValid = if (retimedOrderedClassify) Some(Reg(Vec(ways, Bool()))) else None
    private val classifyLru = if (retimedOrderedClassify) Some(Reg(Bool())) else None
    private val classifyDirty = if (retimedDataCommit) Some(Reg(Vec(ways, Bool()))) else None
    private val classifyCacheable = if (retimedOrderedClassify) Some(Reg(Bool())) else None
    private val classifiedWays = WireDefault(0.U(ways.W))
    private val classifiedHit = WireDefault(true.B)
    private val victimDirty = Reg(Bool())
    private val victimWords = Reg(Vec(8, UInt(64.W)))
    private val releaseBeat = RegInit(0.U(3.W))
    private val probeAddress = Reg(UInt(params.addrWidth.W))
    private val probeSource = Reg(UInt(params.sourceBits.W))
    private val probeHit = Reg(Bool())
    private val probeDirty = Reg(Bool())
    private val probeSlot = if (controlTimingCuts) Some(Reg(UInt(indexBits.W))) else None
    private val probeWords = Reg(Vec(8, UInt(64.W)))
    private val probeBeat = RegInit(0.U(3.W))
    private val probeResume = Reg(UInt(state.getWidth.W))
    private val refillResultPending = WireDefault(false.B)
    private val flushActive = RegInit(false.B)
    private val flushFinished = RegInit(false.B)
    private val flushIndex = RegInit(0.U(indexBits.W))
    // The original pending miss and original acquire-engine slot only.
    // Its response cannot install until the older real ReleaseAck arrives.
    private val overlapIssued = if (writebackOverlap) Some(RegInit(false.B)) else None
    private val acquireAccepted = WireDefault(false.B)
    private val acquireDuringRelease = writebackOverlap.B && maintaining(evictAck) &&
        !flushActive && !pendingBypass && !overlapIssued.getOrElse(false.B)
    private val hitBank = Reg(UInt(3.W))
    private val hitWordSelect = if (parallelWayReads) Some(Reg(UInt(8.W))) else None
    private val readPending = RegInit(false.B)
    private val storePending = RegInit(false.B)
    private val forwardValid = if (retimedDataCommit) Some(RegInit(false.B)) else None
    private val forwardData = if (retimedDataCommit) Some(Reg(UInt(64.W))) else None
    private val forwardMask = if (retimedDataCommit) Some(Reg(UInt(8.W))) else None
    private val forwardBank = if (retimedDataCommit) Some(Reg(UInt(3.W))) else None
    private val forwardRow = if (retimedDataCommit) Some(Reg(UInt(indexBits.W))) else None
    private val readResponses = Module(new I1FlowResponseQueue(new I1DataResponse, responseEntries))
    // Local row events, not a priority chain of dynamic Vec writes. All
    // indices below belong to registered CPU/refill/probe/flush owners.
    private val installRow = WireDefault(false.B)
    private val installIndex = WireDefault(0.U(indexBits.W))
    private val installDirty = WireDefault(false.B)
    private val clearVictim = WireDefault(false.B)
    private val clearProbe = WireDefault(false.B)
    private val clearFlush = WireDefault(false.B)
    private val markStore = WireDefault(false.B)
    private val storeIndex = WireDefault(0.U(indexBits.W))

    private def lineSet(address: UInt): UInt = address(5 + setBits, 6)
    private def lineTag(address: UInt): UInt = tagGeometry.tag(address)
    private val lookupAddress = if (controlTimingCuts) io.upstream.request.bits.address
        else Mux(io.tl.b.valid, io.tl.b.bits.address, io.upstream.request.bits.address)
    private val lookupSet = if (controlTimingCuts) lineSet(lookupAddress) else
        Mux(maintaining(flushScan) && !io.tl.b.valid, flushIndex(setBits - 1, 0), lineSet(lookupAddress))
    private val tagWords = VecInit(tagBanks.map(_.read(lookupSet)))
    // A separate RAM read port removes CPU reply/reissue control from the B
    // probe lookup. Capacity and hit latency are unchanged; no payload copy FF.
    // B wins over flush. Both operations are mutually exclusive consumers,
    // so share a maintenance read port while CPU lookup stays independent.
    private val maintenanceTags = if (controlTimingCuts)
        VecInit(tagBanks.map(_.read(Mux(io.tl.b.valid, lineSet(io.tl.b.bits.address),
            flushIndex(setBits - 1, 0))))) else tagWords
    private val probeTags = maintenanceTags
    private val flushTags = maintenanceTags
    private def slot(address: UInt, way: Int): UInt =
        if (ways == 1) lineSet(address) else Cat(way.U(1.W), lineSet(address))
    private def matches(address: UInt, way: Int): Bool =
        (if (trustedReadOnlyCacheability) true.B else tagGeometry.qualifies(address)) &&
            valid(slot(address, way)) && (if (controlTimingCuts)
                I1TimingMath.equal(tagWords(way), lineTag(address)) else tagWords(way) === lineTag(address))
    private def residentSlot(address: UInt): UInt =
        if (ways == 1) lineSet(address) else Mux(matches(address, 0), slot(address, 0), slot(address, 1))
    private val probeMatches = (0 until ways).map { way =>
        tagGeometry.qualifies(io.tl.b.bits.address) && valid(slot(io.tl.b.bits.address, way)) &&
            (if (controlTimingCuts) I1TimingMath.equal(probeTags(way), lineTag(io.tl.b.bits.address))
             else probeTags(way) === lineTag(io.tl.b.bits.address))
    }
    private val probeAny = probeMatches.reduce(_ || _)
    private val probeIndex = if (ways == 1) lineSet(io.tl.b.bits.address)
        else Mux(probeMatches.head, slot(io.tl.b.bits.address, 0), slot(io.tl.b.bits.address, 1))
    private def slotAddress(index: UInt, flushing: Boolean = false): UInt = {
        val tags = if (flushing) flushTags else tagWords
        val tag = if (ways == 1) tags(0) else tags(index(indexBits - 1))
        tagGeometry.widen(Cat(tag, index(setBits - 1, 0), 0.U(6.W)))
    }
    private def touch(index: UInt): Unit = replacement.foreach { lru =>
        lru(index(setBits - 1, 0)) := !index(indexBits - 1)
    }
    // Ordered hits already retain their index/read/store ownership for SRAM
    // completion. Commit metadata from those registers, without a new stage.
    // A simultaneous new victim/probe must see the older pending write/touch.
    private val deferredHitMetadata = controlTimingCuts && orderedAdmission && ways == 2
    private def pendingStore(index: UInt): Bool = deferredHitMetadata.B &&
        readPending && storePending && classifiedHit && pendingIndex === index
    private def dirtyAt(index: UInt): Bool = dirty(index) || pendingStore(index) ||
        (if (retimedDataCommit) forwardValid.get && forwardRow.get === index else false.B)
    if (deferredHitMetadata) {
        when(readPending && classifiedHit) {
            touch(pendingIndex)
            when(storePending) {
                if (!retimedDataCommit) {
                    if (controlTimingCuts) { markStore := true.B; storeIndex := pendingIndex }
                    else dirty(pendingIndex) := true.B
                }
            }
        }
    }
    if (retimedDataCommit) when(forwardValid.get) {
        // Use the already required physical-collision shadow to commit
        // dirty bits too. The live retained tag match no longer fans through
        // a dynamic 512-row dirty write. dirtyAt forwards both pending edges.
        markStore := true.B; storeIndex := forwardRow.get
    }
    private val request = io.upstream.request.bits
    private val found = (0 until ways).map(matches(request.address, _)).reduce(_ || _)
    private val replacementChoice = if (ways == 2) {
        if (deferredHitMetadata)
            Mux(readPending && pendingIndex(setBits - 1, 0) === lineSet(request.address),
                !pendingIndex(indexBits - 1), replacement.get(lineSet(request.address)))
        else replacement.get(lineSet(request.address))
    } else false.B
    private val victim = if (ways == 1) lineSet(request.address) else {
        val first = slot(request.address, 0)
        val second = slot(request.address, 1)
        Mux(!valid(first), first, Mux(!valid(second), second,
            Cat(replacementChoice, lineSet(request.address))))
    }
    private val index = Mux(found, residentSlot(request.address), victim)
    if (retimedOrderedClassify) {
        val hits = (0 until ways).map { way =>
            // A real cached reply/write is gated by retained !pendingBypass;
            // eviction separately requires the captured complete-access PMA.
            // Do not repeat a wide aperture check before retained tag match.
            classifyValid.get(way) && I1TimingMath.equal(victimTags.get(way), lineTag(pending.address))
        }
        val hit = hits.reduce(_ || _)
        classifiedWays := VecInit(hits).asUInt
        // The acceptance edge retains only the SET, valid bits and forwarded
        // LRU bit. Choose its victim way on the already-existing classification
        // edge, not through live PA -> valid/LRU -> pending-index capture.
        val victimWay = classifyValid.get(0) && (!classifyValid.get(1) || classifyLru.get)
        val chosen = Cat(Mux(hit, !hits.head, victimWay), pending.address(5 + setBits, 6))
        val cacheable = classifyCacheable.get
        val evict = cacheable && Mux(hit, pendingBypass, classifyValid.get.asUInt.andR)
        val phase = Mux(evict, evictCapture, Mux(pendingBypass, bypassSend, Mux(hit, idle, acquire)))
        classifiedHit := !classifyPending.get || (!pendingBypass && hit)
        when(classifyPending.get) {
            state := phase
            pendingIndex := chosen
            // A hit may consume-and-replace with a new CPU owner now. Persist
            // the selected victim ONLY for a miss/eviction; even an invalid
            // way1 miss must install into that chosen row after this marker.
            when(phase === evictCapture || phase === acquire) { pendingIndexStorage := chosen }
            if (retimedDataCommit) when(phase === evictCapture) {
                victimDirty := Mux(chosen(indexBits - 1), classifyDirty.get(1), classifyDirty.get(0))
            }
            assert(PopCount(hits) <= 1.U, "retimed cache owner has duplicate resident tags")
            when(!pendingBypass) {
                assert(classifyCacheable.get && tagGeometry.qualifies(pending.address),
                    "retained cached owner lost complete-access aperture proof")
            }
        }
    }
    // Both RAM endpoints are line aligned. An access <=8B can cross the
    // aperture END only from its last aligned beat. Decode the constant
    // window once, and check only three lane bits in that final beat.
    // This preserves even malformed unaligned input length semantics.
    private val lastLane = MuxLookup(request.size, 0.U(3.W))(
        (0 to 3).map(s => s.U -> (8 - (1 << s)).U(3.W)))
    private val lastBeat = request.address(63, 3) === ((base + bytes - 1) >> 3).U
    private val cacheable = I1AddressWindow.contains(request.address, base, bytes) &&
        (!lastBeat || request.address(2, 0) <= lastLane)
    when(io.upstream.request.valid) {
        assert(cacheable === (request.address >= base.U(65.W) &&
            (request.address +& (1.U(64.W) << request.size)) <= (base + bytes).U(65.W)),
            "compact cache range must preserve the complete access at the aperture end")
    }
    private val ordinary = if (trustedReadOnlyCacheability) io.readCacheable.get
        else cacheable && !request.atomic && !request.virtualized && !request.uncached
    if (trustedReadOnlyCacheability) when(io.upstream.request.valid) {
        assert(!request.write && !request.atomic && !request.virtualized,
            "trusted coherent IF owner must remain physical read-only")
        assert(io.readCacheable.get === (cacheable && !request.uncached),
            "trusted coherent IF cacheability contradicts physical/noAllocate policy")
    }
    private val bypass = !ordinary
    private val victimValid = (0 until ways).map(w => valid(slot(request.address, w))).reduce(_ && _)
    private val needsEviction = if (controlTimingCuts)
        cacheable && Mux(found, bypass, victimValid)
        else cacheable && valid(index) && (!found || bypass)
    private val readHit = ordinary && found && !request.write
    private val writeHit = ordinary && found && request.write
    private val readCapacity = readResponses.io.count +& readPending.asUInt < responseEntries.U
    private val noReadOutstanding = readResponses.io.count === 0.U && !readPending
    private val cpuFire = io.upstream.request.fire
    // Reuse the same pending/SRAM owner only after its actual successful
    // response handshake. No early store acknowledgement or extra miss slot.
    private val retiringMiss = missTurnover.B && maintaining(missResponse) &&
        io.upstream.response.fire && !missResult.error
    private val acceptingPhase = in(idle) || retiringMiss
    if (retimedOrderedClassify) {
        classifyPending.get := cpuFire
        val acceptedLegacyIndex = RegEnable(index, cpuFire)
        when(classifyPending.get && classifyCacheable.get && !reset.asBool) {
            assert(pendingIndex === acceptedLegacyIndex,
                "deferred victim-way choice changed invalid-first/LRU/forwarded-hit ownership")
        }
        val acceptedLegacyPhase = RegEnable(Mux(needsEviction, evictCapture,
            Mux(bypass, bypassSend, Mux(found, idle, acquire))), cpuFire)
        when(classifyPending.get && !reset.asBool) {
            assert(state === acceptedLegacyPhase,
                "retimed cache classification changed the accepted legacy hit/miss/bypass phase")
        }
    }
    private val cpuRead = cpuFire && ordinary && found
    private val evictRead = cpuFire && needsEviction
    private val probeRead = io.tl.b.fire
    private val flushRead = maintaining(flushScan) && !io.tl.b.valid && valid(flushIndex)
    private val readRow = Mux(maintaining(probeCapture), probeSlot.getOrElse(0.U),
        Mux(in(evictCapture) && flushActive, flushIndex, pendingIndex))
    // A write hit is already accepted/authorized. Commit it from the retained
    // owner during its existing response cycle, not through live DT -> tag ->
    // BRAM WE. No response stage, line owner or request capacity is added.
    private val writeHitCommit = retimedDataCommit.B && readPending && storePending && classifiedHit
    if (retimedDataCommit) {
        forwardValid.get := writeHitCommit
        when(readPending && storePending) {
            forwardData.get := pending.data; forwardMask.get := pending.mask
            forwardBank.get := hitBank; forwardRow.get := pendingIndex
        }
        when(writeHitCommit) {
            assert(classifyPending.get && pending.write && !pendingBypass &&
                PopCount(classifiedWays) === 1.U, "cache write commit has no accepted unique owner")
        }
    }
    private def forwardCollision(word: UInt, bank: UInt, row: UInt): UInt = if (retimedDataCommit) {
        // Explicit write-first semantics for every same-edge physical row
        // collision, including masked CPU reads, probe and victim capture.
        // This bounded shadow is hazard metadata, not a request/response slot.
        val collision = forwardValid.get && forwardRow.get === row && forwardBank.get === bank
        val mask = forwardMask.get & Fill(8, collision)
        Cat((7 to 0 by -1).map(i =>
            Mux(mask(i), forwardData.get(8 * i + 7, 8 * i), word(8 * i + 7, 8 * i))))
    } else word
    private val wayReadWords = if (parallelWayReads) {
        val set = Mux(io.tl.b.valid, lineSet(io.tl.b.bits.address),
            Mux(maintaining(flushScan), flushIndex(setBits - 1, 0), lineSet(request.address)))
        // Pure SRAM reads need no architectural authority. Always prepare
        // both ways; ONLY retained ownership/response state may expose data.
        // This removes live DT permission/fire from the BRAM read enables.
        Some(VecInit((0 until 8).map(i => VecInit(dataWays(i).map(_.read(set, true.B).asUInt)))))
    } else None
    private val readWords = VecInit((0 until 8).map { i =>
        if (parallelWayReads) {
            forwardCollision(Mux(readRow(indexBits - 1),
                wayReadWords.get(i)(1), wayReadWords.get(i)(0)), i.U, readRow)
        } else {
            val enabled = probeRead || evictRead || flushRead || (cpuRead && request.address(5, 3) === i.U)
            data(i).read(Mux(probeRead, probeIndex,
                Mux(flushRead, flushIndex, index)), enabled).asUInt
        }
    })
    // Probe capture has its OWN retained B owner. It must not inherit the
    // CPU's live tag/victim selection through a shared readRow mux. For a
    // victim, resolve collision forwarding independently in BOTH physical
    // ways first; the late selected way then crosses only the final mux.
    // Same SRAMs, capture edges and payload registers; no extra line slot.
    private def maintenanceWords(row: UInt): Vec[UInt] = VecInit((0 until 8).map { bank =>
        val perWay = (0 until 2).map { way =>
            forwardCollision(wayReadWords.get(bank)(way), bank.U,
                Cat(way.U(1.W), row(setBits - 1, 0)))
        }
        Mux(row(indexBits - 1), perWay(1), perWay(0))
    })
    private val probeReadWords = if (parallelWayReads) maintenanceWords(probeSlot.get) else readWords
    private val victimReadWords = if (parallelWayReads)
        maintenanceWords(Mux(flushActive, flushIndex, pendingIndex)) else readWords
    private val cpuReadRaw = if (parallelWayReads) {
        // Select the word independently in each way, THEN choose the owner.
        // Do not distribute late tag/way selection through eight word muxes.
        val selected = (0 until 2).map(way =>
            Mux1H(hitWordSelect.get, VecInit((0 until 8).map(i => wayReadWords.get(i)(way)))))
        // This payload is consumed ONLY by a retained cached hit. It must
        // not use probe/eviction/flush readRow or the encoded cache phase.
        val way = if (retimedOrderedClassify) !classifiedWays(0) else pendingIndex(indexBits - 1)
        Mux(way, selected(1), selected(0))
    } else Mux1H(UIntToOH(hitBank, 8), readWords)
    private val cpuReadRow = Cat(
        (if (retimedOrderedClassify) !classifiedWays(0) else pendingIndex(indexBits - 1)),
        pending.address(5 + setBits, 6))
    private val cpuReadWord = if (parallelWayReads)
        forwardCollision(cpuReadRaw, hitBank, cpuReadRow) else cpuReadRaw
    private def merge(oldWord: UInt, write: I1DataRequest): UInt = Cat((7 to 0 by -1).map { i =>
        Mux(write.mask(i), write.data(8 * i + 7, 8 * i), oldWord(8 * i + 7, 8 * i))
    })

    // B wins arbitration over a new CPU request. Read hits use the synchronous SRAM
    // output; masked write hits update the byte lanes directly. Both return through
    // the same ordered response queue. Independent read hits may be captured while one
    // line is being acquired, but their responses remain behind the older miss.
    io.prefetchBusy := false.B
    io.flushDone := flushFinished
    // A queued uncached/atomic CPU request may be behind a probing DMA at the
    // home. Never make B depend on that CPU reply. A completed refill is first
    // installed, then probed from missResponse, so its new tag/data are visible.
    io.tl.b.ready := in(idle) || in(acquire) ||
        (maintaining(fill) && !refillResultPending) || maintaining(missResponse) ||
        in(bypassSend) || maintaining(bypassResponse) || maintaining(flushScan)
    private val probing = maintaining(probeCapture) || maintaining(probeSend)
    if (parallelOrderedControl) when(probing && !reset.asBool) {
        assert(PopCount(probeResume) === 1.U, "probe resume lost its one-hot response owner")
    }
    private val bypassReply = maintaining(bypassResponse) || (probing && phaseIs(probeResume, bypassResponse))
    private val missReply = maintaining(missResponse) || (probing && phaseIs(probeResume, missResponse))
    private val queuedReply = maintaining(idle) || (probing && phaseIs(probeResume, idle))
    private val retainedBypassSending = in(bypassSend) ||
        (controlTimingCuts.B && probing && phaseIs(probeResume, bypassSend))
    val hitUnderMiss = (in(acquire) || maintaining(fill)) && readHit &&
        index =/= pendingIndex && readCapacity
    // IF has one ordered physical requester. Accept any next address only
    // when no old hit remains, or the FINAL older hit is leaving this cycle.
    // Unlike tag-dependent hit/miss admission this removes the fetch reply ->
    // address/tag -> READY loop without adding a word-fetch cycle. No miss
    // can overtake a queued older hit. Uncached offers may need bypassSend.
    private val finalHitLeaving = io.upstream.response.fire &&
        (readResponses.io.count +& readPending.asUInt) === 1.U
    private val orderedRoom = noReadOutstanding || finalHitLeaving
    if (retimedOrderedClassify) when(!reset.asBool) {
        for (phase <- Seq(evictSend, evictAck, fill, missResponse, bypassResponse, probeCapture, probeSend, flushScan)) {
            assert((maintenanceState === phase) === (state === phase),
                "late hit classification changed an already owned maintenance phase")
        }
        when(classifyPending.get && !in(idle)) {
            assert(!readResponses.io.deq.valid,
                "a newly classified miss/bypass overtook a prior queued hit")
        }
    }
    io.upstream.request.ready := (if (orderedAdmission)
        acceptingPhase && orderedRoom && !io.tl.b.valid && !io.flushRequest
        else !io.tl.b.valid && !io.flushRequest &&
        Mux(in(idle), Mux(readHit || writeHit, readCapacity,
            noReadOutstanding && Mux(bypass && !needsEviction, io.downstream.request.ready, true.B)),
            hitUnderMiss))
    // IF bypass leaves ONLY from the already retained pending owner. No
    // live translation -> tag/victim -> native request-admission path.
    // Normal SRAM hits keep their existing acceptance/response edges.
    io.downstream.request.valid := (retainedBypassSending &&
        (if (controlTimingCuts) true.B else !io.tl.b.valid)) ||
        (!retainedOrderedBypass.B && in(idle) &&
            (if (orderedAdmission) orderedRoom else noReadOutstanding) &&
            io.upstream.request.valid && bypass && !io.flushRequest &&
            !needsEviction && !io.tl.b.valid)
    io.downstream.request.bits := Mux(retainedBypassSending, pending, request)
    io.downstream.response.ready := bypassReply && io.upstream.response.ready
    readResponses.io.enq.valid := readPending && classifiedHit
    readResponses.io.enq.bits.data := Mux(storePending, 0.U, cpuReadWord)
    readResponses.io.enq.bits.error := false.B
    readResponses.io.enq.bits.pageFault := false.B
    readResponses.io.deq.ready := io.upstream.response.ready && queuedReply
    assert(!readPending || readResponses.io.enq.ready, "cache hit response queue overflow")
    // Probes must not withdraw an already offered CPU response. Keep the older
    // reply live under B/C backpressure; queued hit replies stay behind a miss.
    io.upstream.response.valid := (queuedReply && readResponses.io.deq.valid) || missReply ||
        (bypassReply && io.downstream.response.valid)
    if (retimedOrderedClassify) {
        // Combine registered phase/occupancy before the late two-way hit
        // result. Do not serialize tag -> enqueue VALID -> FIFO flow VALID
        // -> response-kind mux. The same queue still owns stored responses.
        val legacyValid = (queuedReply && readResponses.io.deq.valid) || missReply ||
            (bypassReply && io.downstream.response.valid)
        val storedOrKnownHit = queuedReply && (!readResponses.empty ||
            (readPending && !classifyPending.get))
        val classifyingHit = queuedReply && readPending && classifyPending.get && !pendingBypass
        io.upstream.response.valid := storedOrKnownHit ||
            (classifyingHit && classifiedWays.orR) || missReply ||
            (bypassReply && io.downstream.response.valid)
        when(!reset.asBool) {
            assert(io.upstream.response.valid === legacyValid,
                "parallel cache response admission changed stored/flow/miss/bypass ownership")
        }
    }
    io.upstream.response.bits := Mux(missReply, missResult,
        Mux(bypassReply, io.downstream.response.bits, readResponses.io.deq.bits))
    if (parallelOrderedControl) {
        // Flatten the existing flow/stored/miss/bypass choices. In particular
        // a live BRAM word no longer crosses FIFO-flow then response-kind
        // muxes. Fold store-zero and masked collision forwarding into the
        // source masks BEFORE the payload reduction, not after word/way mux.
        val hitSource = !missReply && !bypassReply
        val live = hitSource && readResponses.empty && !storePending
        val held = hitSource && !readResponses.empty
        val shadow = if (retimedDataCommit)
            forwardValid.get && forwardRow.get === cpuReadRow && forwardBank.get === hitBank else false.B
        val original = Mux(missReply, missResult.data,
            Mux(bypassReply, io.downstream.response.bits.data, readResponses.io.deq.bits.data))
        val data = Cat((7 to 0 by -1).map { byte =>
            val forwarded = shadow && forwardMask.map(_(byte)).getOrElse(false.B)
            if (parallelWayReads) {
                // Flatten SRAM word/way + live/held/miss/native selection
                // into ONE reduction. The late BRAM payload does not first
                // pass a word mux, then a way mux, then a response-kind mux.
                val sram = for (bank <- 0 until 8; way <- 0 until 2) yield
                    ((live && !forwarded && hitWordSelect.get(bank) && classifiedWays(way)),
                        wayReadWords.get(bank)(way)(byte * 8 + 7, byte * 8))
                I1ExecuteDatapath.operand(
                    Seq(missReply, !missReply && bypassReply, held, live && forwarded) ++ sram.map(_._1),
                    Seq(missResult.data, io.downstream.response.bits.data, readResponses.stored.data,
                        forwardData.getOrElse(0.U(64.W))).map(_(byte * 8 + 7, byte * 8)) ++ sram.map(_._2))
            } else I1ExecuteDatapath.operand(
                Seq(missReply, !missReply && bypassReply, held, live && !forwarded, live && forwarded),
                Seq(missResult.data, io.downstream.response.bits.data, readResponses.stored.data,
                    cpuReadRaw, forwardData.getOrElse(0.U(64.W))).map(_(byte * 8 + 7, byte * 8)))
        })
        if (orderedReadOnly && parallelWayReads && retimedOrderedClassify) {
            // Read-only payload needs the matching WAY, not the complete
            // permission/valid/cacheability decision. A speculative value
            // while response.valid is low has no consumer. The unchanged
            // valid path still authorizes every actual response.
            val words = (0 until 2).map(way => Mux1H(hitWordSelect.get,
                VecInit((0 until 8).map(bank => wayReadWords.get(bank)(way)))))
            val wayZeroTag = classifyValid.get(0) &&
                I1TimingMath.equal(victimTags.get(0), lineTag(pending.address))
            val liveWord = Mux(wayZeroTag, words(0), words(1))
            val cached = Mux(readResponses.empty, liveWord, readResponses.stored.data)
            io.upstream.response.bits.data := Mux(missReply, missResult.data,
                Mux(bypassReply, io.downstream.response.bits.data, cached))
        } else io.upstream.response.bits.data := data
        when(io.upstream.response.valid && !reset.asBool) {
            assert(data === original, "fused cache return changed its owned byte/forwarding result")
            assert(io.upstream.response.bits.data === original,
                "prepared read-only cache payload changed an authorized word")
        }
    }
    io.hit := cpuFire && ordinary && found
    io.miss := cpuFire && ordinary && !found
    io.profile.emptySlotMiss := io.miss && !valid(index)
    io.profile.replacementMiss := io.miss && valid(index)
    io.profile.readMiss := io.miss && !request.write
    io.profile.writeMiss := io.miss && request.write
    io.profile.dirtyEviction := cpuFire && needsEviction && dirtyAt(index)
    io.profile.missBlocked := io.upstream.request.valid && !io.upstream.request.ready &&
        (in(evictCapture) || maintaining(evictSend) || maintaining(evictAck) ||
            in(acquire) || maintaining(fill) || maintaining(missResponse))
    io.profile.bypassBlocked := io.upstream.request.valid && !io.upstream.request.ready &&
        (in(bypassSend) || maintaining(bypassResponse))
    io.profile.probeBlocked := io.upstream.request.valid && !io.upstream.request.ready &&
        (maintaining(probeCapture) || maintaining(probeSend) || (in(idle) && io.tl.b.valid))
    io.profile.evictionCycle := in(evictCapture) || maintaining(evictSend) || maintaining(evictAck)
    io.profile.refillCycle := in(acquire) || maintaining(fill)
    readPending := false.B
    storePending := false.B
    when(!io.flushRequest) { flushFinished := false.B }
    when(in(idle) && io.flushRequest && !flushFinished && noReadOutstanding && !io.tl.b.valid) {
        flushActive := true.B
        flushIndex := 0.U
        legacyNextState := flushScan
    }
    when(maintaining(flushScan) && !io.tl.b.valid) {
        // Clearing an already invalid row is a no-op. Do not read a dynamic
        // 512-way valid mux just to authorize clearing that very same row.
        if (controlTimingCuts) clearFlush := true.B
        when(valid(flushIndex)) {
            if (controlTimingCuts) victimTags.get := flushTags
            else victimAddress := slotAddress(flushIndex, flushing = true)
            victimDirty := dirtyAt(flushIndex)
            if (!controlTimingCuts) { valid(flushIndex) := false.B; dirty(flushIndex) := false.B }
            legacyNextState := evictCapture
        }.otherwise {
            when(flushIndex === (lines - 1).U) {
                flushFinished := true.B
                flushActive := false.B
                legacyNextState := idle
            }.otherwise { flushIndex := flushIndex + 1.U }
        }
    }
    if (controlTimingCuts) when(acceptingPhase) {
        // Prepare the existing victim context independently of CPU transfer
        // permission. Only evictCapture/evictSend can consume it, and those
        // states still require the real accepted request and eviction test.
        // No response/native arbitration -> victim-register enable loop.
        victimTags.get := tagWords
        victimDirty := (if (retimedOrderedClassify) false.B else dirtyAt(index))
    }
    if (controlTimingCuts) when(in(evictCapture)) {
        // The existing SRAM victim-capture edge precedes the first C beat.
        // Retain both tag words before live hit/victim-way selection, then
        // reconstruct the victim address from registered ownership here.
        // No eviction cycle, response entry or payload bank is added.
        val row = Mux(flushActive, flushIndex, pendingIndex)
        val tag = if (ways == 1) victimTags.get(0) else victimTags.get(row(indexBits - 1))
        victimAddress := tagGeometry.widen(Cat(tag, row(setBits - 1, 0), 0.U(6.W)))
    }
    if (controlTimingCuts && orderedAdmission) when(acceptingPhase) {
        // Old hit metadata is consumed from the OLD registers at this edge.
        // New payload is unowned until real cpuFire commits phase/credits.
        pending := request
        // Retimed owner chooses the hit way from the already retained tags.
        // The live PA only selects a set/victim, not tag comparison -> CE.
        pendingIndexStorage := (if (retimedOrderedClassify)
            Cat(0.U(1.W), lineSet(request.address)) else index)
        classifyLru.foreach(_ := replacementChoice)
        pendingBypass := bypass
        classifyValid.foreach { bits =>
            for (way <- 0 until ways) { bits(way) := valid(slot(request.address, way)) }
        }
        classifyDirty.foreach { bits =>
            for (way <- 0 until ways) { bits(way) := dirtyAt(slot(request.address, way)) }
        }
        classifyCacheable.foreach(_ := cacheable)
        hitWordSelect.foreach(_ := UIntToOH(request.address(5, 3), 8))
    }
    when(cpuFire) {
        if (orderedAdmission) {
            assert(acceptingPhase && orderedRoom, "ordered cache admission overtook an older reply")
        }
        if (orderedReadOnly) {
            assert(!request.write && !request.atomic, "read-only ordered cache received a write/AMO")
        }
        when(acceptingPhase) {
            if (!controlTimingCuts || !orderedAdmission) {
                pending := request
                pendingIndexStorage := index
                pendingBypass := bypass
            }
        }.otherwise {
            assert(hitUnderMiss, "only independent read hits may pass an outstanding cache miss")
        }
        if (!retimedOrderedClassify) {
            when(needsEviction) {
                if (!controlTimingCuts) {
                    victimAddress := slotAddress(index)
                    victimDirty := dirtyAt(index)
                    valid(index) := false.B
                    dirty(index) := false.B
                }
                legacyNextState := evictCapture
            }.elsewhen(bypass) {
                legacyNextState := (if (retainedOrderedBypass) bypassSend else if (orderedAdmission)
                    Mux(io.downstream.request.ready, bypassResponse, bypassSend) else bypassResponse)
            }.elsewhen(writeHit) {
                if (!deferredHitMetadata) {
                    touch(index)
                    if (controlTimingCuts) { markStore := true.B; storeIndex := index }
                    else dirty(index) := true.B
                }
                readPending := true.B
                storePending := true.B
            }.elsewhen(readHit) {
                if (!deferredHitMetadata) touch(index)
                hitBank := request.address(5, 3)
                readPending := true.B
            }.otherwise { legacyNextState := acquire }
        }
    }
    when(in(evictCapture)) {
        // No CPU/B owner can enter evictCapture. Clear the already captured
        // victim here, before offering Release, instead of feeding response ->
        // next translation/tag -> dynamic 512-bit metadata write in one cycle.
        if (controlTimingCuts && !retimedOrderedClassify) when(!flushActive) {
            clearVictim := true.B
        }
        for (i <- 0 until 8) { victimWords(i) := victimReadWords(i) }
        if (parallelWayReads) when(!reset.asBool) {
            assert(victimReadWords.asUInt === readWords.asUInt,
                "local victim capture changed selected SRAM/forwarded bytes")
        }
        releaseBeat := 0.U
        legacyNextState := evictSend
    }
    if (retimedOrderedClassify) when(phaseIs(stateStorage, evictSend) && !flushActive) {
        // The retained victim words/address already own the release. CPU
        // and B stay blocked until completion, so invalidate in this EXISTING
        // send stage, independently of live classification/tag comparisons.
        assert(maintaining(evictSend), "retained victim clear lost its release phase")
        clearVictim := true.B
    }
    io.tl.c.valid := maintaining(evictSend) || maintaining(probeSend)
    io.tl.c.bits := 0.U.asTypeOf(io.tl.c.bits)
    io.tl.c.bits.opcode := Mux(maintaining(evictSend),
        Mux(victimDirty, TLOpcode.ReleaseData, TLOpcode.Release),
        Mux(probeDirty, TLOpcode.ProbeAckData, TLOpcode.ProbeAck))
    io.tl.c.bits.param := Mux(maintaining(evictSend), TLPermissions.tToN,
        Mux(probeHit, TLPermissions.tToN, 5.U))
    io.tl.c.bits.size := 6.U
    io.tl.c.bits.source := Mux(maintaining(evictSend), 0.U, probeSource)
    io.tl.c.bits.address := Mux(maintaining(evictSend), victimAddress, probeAddress)
    io.tl.c.bits.data := Mux(maintaining(evictSend), victimWords(releaseBeat), probeWords(probeBeat))
    when(io.tl.c.fire && maintaining(evictSend)) {
        when(!victimDirty || releaseBeat === 7.U) { legacyNextState := evictAck }
            .otherwise { releaseBeat := releaseBeat + 1.U }
    }
    when(io.tl.d.fire && io.tl.d.bits.opcode === TLOpcode.ReleaseAck) {
        assert(maintaining(evictAck) && io.tl.d.bits.source === 0.U &&
            !io.tl.d.bits.denied && !io.tl.d.bits.corrupt, "cache ReleaseAck invalid")
        when(flushActive) {
            when(flushIndex === (lines - 1).U) {
                flushFinished := true.B
                flushActive := false.B
                legacyNextState := idle
            }.otherwise {
                flushIndex := flushIndex + 1.U
                legacyNextState := flushScan
            }
        }.otherwise {
            legacyNextState := Mux(pendingBypass, bypassSend,
                Mux(overlapIssued.getOrElse(false.B) || acquireAccepted, fill, acquire))
        }
    }
    when(in(bypassSend) && io.downstream.request.fire) { legacyNextState := bypassResponse }
    when(maintaining(bypassResponse) && io.upstream.response.fire) { legacyNextState := idle }

    // This cache has one pending miss, not four independent line owners.
    // Two is the reusable engine's minimum; retain protocol buffering, not
    // unused four-line FF storage. Does not reduce hit-under-miss admission.
    private val engine = Module(new TileLinkLineAcquireEngine(params, entries = 2,
        internalLineGrant = internalLineGrant))
    engine.io.lineGrant.foreach(_ <> io.lineGrant.get)
    refillResultPending := engine.io.response.valid
    engine.io.request.valid := (in(acquire) || acquireDuringRelease) && !io.tl.b.valid
    engine.io.request.bits.address := Cat(pending.address(63, 6), 0.U(6.W))
    engine.io.request.bits.tag := 0.U
    engine.io.request.bits.grow := TLPermissions.nToT
    engine.io.request.bits.permissionOnly := false.B
    acquireAccepted := engine.io.request.fire
    when(engine.io.request.fire && !acquireDuringRelease) { legacyNextState := fill }
    overlapIssued.foreach { issued =>
        when(engine.io.request.fire && acquireDuringRelease) { issued := true.B }
        when(io.tl.d.fire && io.tl.d.bits.opcode === TLOpcode.ReleaseAck) { issued := false.B }
    }
    engine.io.response.ready := maintaining(fill)
    val fillIndex = maintenanceIndex
    val selected = pending.address(5, 3)
    val writeHitFire = if (retimedDataCommit) writeHitCommit else cpuFire && in(idle) && writeHit
    val hitWriteAddress = if (retimedDataCommit) pending.address else request.address
    val hitWriteData = if (retimedDataCommit) pending.data else request.data
    val hitWriteMask = if (retimedDataCommit) pending.mask else request.mask
    val hitWriteIndex = if (retimedDataCommit) pendingIndex else index
    for (i <- 0 until 8) {
        val original = engine.io.response.bits.data(64 * i + 63, 64 * i)
        val filled = Mux(pending.write && selected === i.U && !engine.io.response.bits.error,
            merge(original, pending), original)
        val hitBankWrite = writeHitFire && hitWriteAddress(5, 3) === i.U
        if (parallelWayReads) {
            if (orderedReadOnly) { assert(!hitBankWrite, "read-only parallel SRAM received a CPU write") }
            when(engine.io.response.fire) { assert(!cpuFire && !probeRead && !flushRead,
                "parallel way SRAM refill overlapped a read owner")
            }
            for (way <- 0 until 2) {
                val fillWay = engine.io.response.fire && fillIndex(indexBits - 1) === way.U
                val hitWay = if (retimedDataCommit)
                    readPending && storePending && !pendingBypass &&
                        classifiedWays(way) && hitWriteAddress(5, 3) === i.U
                    else hitBankWrite && hitWriteIndex(indexBits - 1) === way.U
                when(fillWay || hitWay) {
                    dataWays(i)(way).write(
                        Mux(engine.io.response.fire, fillIndex(setBits - 1, 0), hitWriteIndex(setBits - 1, 0)),
                        Mux(engine.io.response.fire, filled, hitWriteData).asTypeOf(Vec(8, UInt(8.W))),
                        Mux(engine.io.response.fire, 255.U(8.W), hitWriteMask).asBools)
                }
            }
        } else {
            when(engine.io.response.fire || hitBankWrite) {
                data(i).write(Mux(engine.io.response.fire, fillIndex, index),
                    Mux(engine.io.response.fire, filled, request.data).asTypeOf(Vec(8, UInt(8.W))),
                    Mux(engine.io.response.fire, 255.U(8.W), request.mask).asBools)
            }
        }
    }
    when(engine.io.response.fire) {
        assert(engine.io.response.bits.cap === TLPermissions.toT || engine.io.response.bits.error,
            "write-back L1 requires T permission")
        val word = (engine.io.response.bits.data >> (selected << 6))(63, 0)
        when(!engine.io.response.bits.error) {
            if (tagConfig.compact) assert(tagGeometry.contains(pending.address), "tag install outside aperture")
            for (way <- 0 until ways) {
                when((if (ways == 1) true.B else fillIndex(indexBits - 1) === way.U)) {
                    tagBanks(way).write(fillIndex(setBits - 1, 0), lineTag(pending.address))
                }
            }
            if (controlTimingCuts) {
                installRow := true.B; installIndex := fillIndex
                installDirty := (if (orderedReadOnly) false.B else pending.write)
            } else { valid(fillIndex) := true.B; dirty(fillIndex) := pending.write }
            touch(fillIndex)
        }
        missResult.data := Mux(pending.write, 0.U, word)
        missResult.error := engine.io.response.bits.error
        missResult.pageFault := false.B
        legacyNextState := missResponse
    }
    if (fetchPredecode) {
        // Prepare format bits BEFORE the existing SRAM edge. Tag classification
        // and real response ownership still guard every visible byte.
        val classReads = VecInit(fetchClassBanks.map(_.read(lineSet(request.address))))
        val preparedClasses = Reg(Vec(ways, UInt(8.W)))
        when(cpuFire) {
            for (way <- 0 until ways) {
                preparedClasses(way) := classReads(way)(request.address(5, 3))
            }
        }
        val classReplies = Module(new Queue(UInt(8.W), responseEntries, pipe = false, flow = true))
        classReplies.io.enq.valid := readResponses.io.enq.valid
        classReplies.io.enq.bits := (if (orderedReadOnly && parallelWayReads && retimedOrderedClassify)
            Mux(classifyValid.get(0) && I1TimingMath.equal(victimTags.get(0), lineTag(pending.address)),
                preparedClasses(0), preparedClasses(1)) else Mux1H(classifiedWays, preparedClasses))
        classReplies.io.deq.ready := readResponses.io.deq.ready
        when(!reset.asBool) {
            assert(classReplies.io.deq.valid === readResponses.io.deq.valid &&
                classReplies.io.enq.ready === readResponses.io.enq.ready &&
                classReplies.io.count === readResponses.io.count,
                "parcel metadata must retain exactly the existing hit-response owners")
        }
        val missClasses = Reg(UInt(8.W))
        when(engine.io.response.fire) {
            val classes = VecInit((0 until 8).map(i =>
                I1InstructionPredecode.classify(engine.io.response.bits.data(64 * i + 63, 64 * i))))
            missClasses := classes(pending.address(5, 3))
            when(!engine.io.response.bits.error) {
                for (way <- 0 until ways) {
                    when(maintenanceIndex(indexBits - 1) === way.U) {
                        fetchClassBanks(way).write(maintenanceIndex(setBits - 1, 0), classes)
                    }
                }
            }
        }
        io.fetchClasses := Mux(missReply, missClasses,
            Mux(bypassReply, I1InstructionPredecode.classify(io.downstream.response.bits.data),
                classReplies.io.deq.bits))
        when(io.upstream.response.valid && !io.upstream.response.bits.error && !reset.asBool) {
            assert(io.fetchClasses === I1InstructionPredecode.classify(io.upstream.response.bits.data),
                "cached parcel metadata differs from the exact owned instruction bytes")
        }
    }
    when(maintaining(missResponse) && io.upstream.response.fire) { legacyNextState := idle }
    io.tl.a <> engine.io.a
    engine.io.d.valid := io.tl.d.valid && io.tl.d.bits.opcode =/= TLOpcode.ReleaseAck
    engine.io.d.bits := io.tl.d.bits
    io.tl.d.ready := Mux(io.tl.d.bits.opcode === TLOpcode.ReleaseAck, maintaining(evictAck), engine.io.d.ready)
    io.tl.e <> engine.io.e

    when(io.tl.b.fire) {
        assert(io.tl.b.bits.opcode === TLOpcode.ProbeBlock && io.tl.b.bits.size === 6.U &&
            io.tl.b.bits.param === TLPermissions.toN, "private cache expects an invalidation probe")
        probeAddress := io.tl.b.bits.address
        probeSource := io.tl.b.bits.source
        // B and the pending CPU reply may both handshake in this cycle. Resume
        // idle in that case, not a response state whose credit was consumed.
        if (!controlTimingCuts) {
            probeResume := Mux((maintaining(bypassResponse) || maintaining(missResponse)) &&
                io.upstream.response.fire, idle, state)
        }
        probeHit := probeAny
        probeSlot.foreach(_ := probeIndex)
        probeDirty := Mux1H(probeMatches.zipWithIndex.map { case (hit, way) =>
            hit -> dirtyAt(slot(io.tl.b.bits.address, way))
        })
        assert(PopCount(VecInit(probeMatches)) <= 1.U, "duplicate resident cache tags")
        if (!controlTimingCuts) {
            for (way <- 0 until ways) {
                when(probeMatches(way)) {
                    valid(slot(io.tl.b.bits.address, way)) := false.B
                    dirty(slot(io.tl.b.bits.address, way)) := false.B
                }
            }
        }
        legacyNextState := probeCapture
    }
    when(maintaining(probeCapture)) {
        // The B owner has already captured hit/index/dirty and SRAM read.
        // No CPU or second B can enter until ProbeAck. Invalidate here,
        // before C is offered, not through live B tag/qualification at fire.
        if (controlTimingCuts) clearProbe := probeHit
        for (i <- 0 until 8) { probeWords(i) := probeReadWords(i) }
        if (parallelWayReads) when(!reset.asBool) {
            assert(probeReadWords.asUInt === readWords.asUInt,
                "local probe capture changed selected SRAM/forwarded bytes")
        }
        probeBeat := 0.U
        legacyNextState := probeSend
    }
    private val probeReplyConsumed = probing && (bypassReply || missReply) && io.upstream.response.fire
    private val probeBypassAccepted = controlTimingCuts.B && probing &&
        phaseIs(probeResume, bypassSend) && io.downstream.request.fire
    if (controlTimingCuts) {
        val legacyProbeResume = Reg(UInt(state.getWidth.W))
        when(io.tl.b.fire) {
            legacyProbeResume := Mux((maintaining(bypassResponse) || maintaining(missResponse)) &&
                io.upstream.response.fire, idle,
                Mux(in(bypassSend) && io.downstream.request.fire, bypassResponse, state))
        }
        when(probeBypassAccepted) { legacyProbeResume := bypassResponse }
        when(probeReplyConsumed) { legacyProbeResume := idle }
        when(probing && !reset.asBool) {
            assert(probeResume === legacyProbeResume, "prepared probe resume changed accepted owner")
        }
        // Prepare the existing resume owner before B acceptance. A live CPU
        // reply or retained bypass can advance at the same edge as B: record
        // those local events directly, not through a B/fire priority mux.
        when(!probing) { probeResume := state }
        when(in(bypassSend) && io.downstream.request.fire || probeBypassAccepted) {
            probeResume := bypassResponse
        }
        when((maintaining(bypassResponse) || maintaining(missResponse)) &&
            io.upstream.response.fire || probeReplyConsumed) { probeResume := idle }
    } else {
        when(probeBypassAccepted) { probeResume := bypassResponse }
        when(probeReplyConsumed) { probeResume := idle }
    }
    when(io.tl.c.fire && maintaining(probeSend)) {
        when(!probeDirty || probeBeat === 7.U) {
            legacyNextState := Mux(probeReplyConsumed, idle,
                Mux(probeBypassAccepted, bypassResponse, probeResume))
        }
            .otherwise { probeBeat := probeBeat + 1.U }
    }
    if (parallelOrderedControl) {
        // Read-only hit completion is independent of miss/bypass priority.
        readPending := (if (retimedOrderedClassify) cpuFire else cpuFire && ordinary && found)
        storePending := (if (orderedReadOnly) false.B else cpuFire && request.write)
        when(cpuFire) { hitBank := request.address(5, 3) }
        val b = io.tl.b.fire
        val flushStart = in(idle) && io.flushRequest && !flushFinished &&
            noReadOutstanding && !io.tl.b.valid
        val scanning = maintaining(flushScan) && !io.tl.b.valid
        val releaseAck = io.tl.d.fire && io.tl.d.bits.opcode === TLOpcode.ReleaseAck
        val evictDone = io.tl.c.fire && maintaining(evictSend) && (!victimDirty || releaseBeat === 7.U)
        val probeDone = io.tl.c.fire && maintaining(probeSend) && (!probeDirty || probeBeat === 7.U)
        val postRelease = Mux(flushActive, Mux(flushIndex === (lines - 1).U, idle, flushScan),
            Mux(pendingBypass, bypassSend,
                Mux(overlapIssued.getOrElse(false.B) || acquireAccepted, fill, acquire)))
        val postProbe = Mux(probeReplyConsumed, idle,
            Mux(probeBypassAccepted, bypassResponse, probeResume))
        // Disjoint transition events, not a nested miss/PMA/hit priority mux.
        // B wins the few legal simultaneous response/offer handoffs.
        val transitions = Seq(
            (!retimedOrderedClassify.B && cpuFire && needsEviction) -> evictCapture,
            (!retimedOrderedClassify.B && cpuFire && bypass && !needsEviction) -> bypassSend,
            (!retimedOrderedClassify.B && cpuFire && ordinary && !found && !victimValid) -> acquire,
            flushStart -> flushScan,
            (scanning && valid(flushIndex)) -> evictCapture,
            (scanning && !valid(flushIndex) && flushIndex === (lines - 1).U) -> idle,
            (in(evictCapture)) -> evictSend,
            evictDone -> evictAck,
            releaseAck -> postRelease,
            (in(bypassSend) && io.downstream.request.fire && !b) -> bypassResponse,
            (maintaining(bypassResponse) && io.upstream.response.fire && !b) -> idle,
            (engine.io.request.fire && !acquireDuringRelease) -> fill,
            engine.io.response.fire -> missResponse,
            (maintaining(missResponse) && io.upstream.response.fire && !b) -> idle,
            b -> probeCapture,
            (maintaining(probeCapture)) -> probeSend,
            probeDone -> postProbe)
        val changing = transitions.map(_._1).reduce(_ || _)
        val next = Mux(changing, Mux1H(transitions), state)
        stateStorage := next
        when(!reset.asBool) {
            assert(PopCount(transitions.map(_._1)) <= 1.U, "ordered cache transition events are not disjoint")
            assert(next === legacyNextState, "ordered cache phase changed relative to precise legacy transition")
        }
    }
    if (controlTimingCuts) {
        assert(PopCount(Seq(installRow, clearVictim, clearProbe, clearFlush)) <= 1.U,
            "cache metadata has multiple maintenance owners")
        // Assertion-only legacy lookup is shared, not re-expanded once per
        // row into 512 separate 512-way muxes by the pinned GSIM lowering.
        val legacyFlushClear = clearFlush && valid(flushIndex)
        val nextValidRows = Wire(Vec(lines, Bool()))
        val nextDirtyRows = Wire(Vec(lines, Bool()))
        for (row <- 0 until lines) {
            val install = installRow && installIndex === row.U
            val clear = (clearVictim && maintenanceIndex === row.U) ||
                (clearProbe && probeSlot.get === row.U) || (clearFlush && flushIndex === row.U)
            val store = markStore && storeIndex === row.U
            // Local next-bit equations, not a wide clear-qualified CE/hold
            // mux. No payload storage or transaction ownership is added.
            val nextValid = (valid(row) || install) && !clear
            val nextDirty = Mux(install, installDirty, dirty(row) || store) && !clear
            valid(row) := nextValid
            dirty(row) := nextDirty
            nextValidRows(row) := nextValid
            nextDirtyRows(row) := nextDirty
        }
        // Bitmaps check EVERY row at once. Do not create 3*lines separate
        // event-driven fatal monitors in the pinned GSIM evaluator.
        val zeroRows = 0.U(lines.W)
        val installMask = Mux(installRow, UIntToOH(installIndex, lines), zeroRows)
        val storeMask = Mux(markStore, UIntToOH(storeIndex, lines), zeroRows)
        val legacyClearMask =
            Mux(clearVictim, UIntToOH(pendingIndex, lines), zeroRows) |
            Mux(clearProbe, UIntToOH(probeSlot.get, lines), zeroRows) |
            Mux(legacyFlushClear, UIntToOH(flushIndex, lines), zeroRows)
        val legacyValid = (valid.asUInt | installMask) & ~legacyClearMask
        val legacyDirty = ((dirty.asUInt & ~installMask) |
            Mux(installDirty, installMask, zeroRows) | (storeMask & ~installMask)) & ~legacyClearMask
        when(!reset.asBool) {
            assert(nextValidRows.asUInt === legacyValid,
                "local valid equation changed legacy metadata state")
            assert(nextDirtyRows.asUInt === legacyDirty,
                "local dirty equation changed legacy metadata state")
            assert((dirty.asUInt & ~valid.asUInt) === zeroRows,
                "invalid cache row retained dirty ownership")
        }
        when(maintaining(probeCapture) || maintaining(probeSend)) {
            assert(!cpuFire && !io.tl.b.fire, "probe metadata owner was overtaken")
        }
        if (retainedOrderedBypass) when(io.downstream.request.valid) {
            assert(retainedBypassSending && pendingBypass,
                "ordered native bypass must use the retained authorized owner")
        }
    }
}
