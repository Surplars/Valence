package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLParams, TLOpcode, TLPermissions}
import soc.ip.tilelink.TileLinkLineAcquireEngine

/** Opt-in read-miss concurrency. CPU replies retain acceptance order; maintenance
  * has independent ownership, and store/bypass/flush operations remain barriers.
  * One reserved set per MSHR deliberately excludes merging and same-set replay.
  */
class NonBlockingCoherentLineCache(
    base: BigInt = BigInt("80010000", 16), bytes: BigInt = 8192, lines: Int = 128,
    params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 2),
    ways: Int = 2, concurrency: CoherentCacheConcurrency = CoherentCacheConcurrency(2),
    tagConfig: CacheTagConfig = CacheTagConfig.FullWidth,
    postedConfig: Option[PostedStoreMergeConfig] = None
) extends CoherentLineCacheModule(params, postedConfig) {
    require(Set(2, 4).contains(concurrency.readMshrs))
    require(lines >= 4 && lines <= 512 && isPow2(lines))
    require(Set(1, 2).contains(ways) && lines / ways >= 2)
    require(bytes >= lines * 64 && bytes % 64 == 0 && base % 64 == 0)
    require(params.addrWidth == 64 && params.dataWidth == 64 &&
        params.sourceBits >= concurrency.sourceBits && params.sinkBits >= concurrency.sinkBits)
    private val mshrCount = concurrency.readMshrs
    require(lines / ways >= mshrCount, "each read MSHR needs an independently reservable set")
    private val mshrBits = log2Ceil(mshrCount)
    val observationStorePrefetch = WireDefault(0.U.asTypeOf(new CheckedStorePrefetchObservation(mshrBits)))
    private val responseCount = concurrency.responseEntries
    private val ticketBits = log2Ceil(responseCount)
    private val indexBits = log2Ceil(lines)
    private val setBits = log2Ceil(lines / ways)
    postedConfig.foreach { c =>
        require(c.enabled && c.readMshrs == mshrCount && c.readMshrs == 2 &&
            c.cacheSets == lines / ways && c.cacheWays == ways &&
            c.responseEntries == responseCount && c.writebackEntries == concurrency.writebackEntries,
            "posted owner must use the exact original cache resources")
        c.requireCacheAperture(base, bytes)
    }
    require(!concurrency.postedPrefetchCoexistence || postedConfig.exists(_.enabled),
        "posted/prefetch coexistence requires an enabled posted owner")
    private val posted = postedConfig.map(c => Module(new PostedStoreMerge(c)))
    val observationPosted = postedConfig.map(c => WireDefault(0.U.asTypeOf(new PostedStoreCacheObservation(c))))
    val observationLineWrite = WireDefault(0.U.asTypeOf(new CacheLineWriteObservation))
    // Exhaustion falls back to the legacy path, whose CPU response can precede
    // a dirty victim ReleaseAck. Conservatively retain the complete accepted
    // legacy cache episode, without claiming per-owner early reclamation.
    private val fallbackDrainActive = postedConfig.map(_ => RegInit(false.B))
    private val fallbackDrainEpoch = postedConfig.map(c => Reg(UInt(c.epochBits.W)))
    private val postedBusy = posted.map(_.io.busy).getOrElse(false.B) || fallbackDrainActive.getOrElse(false.B)
    private val postedEpoch = posted.map(_.io.episodeActive).getOrElse(false.B)
    private val postedIntent = io.posted.map(p => p.requestProof.valid && io.upstream.request.valid).getOrElse(false.B)
    // A proof-bearing offer may avoid new posted responsibility only on the
    // ordinary resident-hit route. This is filled from pre-edge classification,
    // never from READY, accepted, cpuFire, or a downstream handshake.
    private val postedLegacyHit = WireDefault(false.B)
    private val postedPrefetchAllowed = if (concurrency.postedPrefetchCoexistence)
        !postedBusy && (!postedIntent || postedLegacyHit)
    else !postedEpoch && !postedIntent
    private val postedMshr = postedConfig.map(_ => RegInit(VecInit(Seq.fill(mshrCount)(false.B))))
    private val postedContext = postedConfig.map(c => Reg(Vec(mshrCount, new PostedLineContext(c))))
    private val postedReservation = postedConfig.map(c => Reg(Vec(mshrCount, new PostedCacheReservation(c))))
    private val postedAcquired = postedConfig.map(_ => RegInit(VecInit(Seq.fill(mshrCount)(false.B))))
    private val postedInstalled = postedConfig.map(_ => RegInit(VecInit(Seq.fill(mshrCount)(false.B))))
    private def isPosted(i: UInt): Bool = postedMshr.map(_(i)).getOrElse(false.B)
    private val postedAccept = posted.map(_.io.accepted.valid).getOrElse(false.B)
    private val postedNew = posted.map(m => m.io.accepted.valid && m.io.accepted.bits.newLine).getOrElse(false.B)
    private val postedFallbackFire = posted.map(_.io.fallback.fire).getOrElse(false.B)
    for ((owner, boundary) <- posted.zip(io.posted)) {
        owner.io.enq.valid := false.B
        owner.io.enq.bits.request := io.upstream.request.bits
        owner.io.enq.bits.proof := boundary.requestProof.bits
        owner.io.cacheAdmission := 0.U.asTypeOf(owner.io.cacheAdmission)
        owner.io.contextEpoch := boundary.contextEpoch
        owner.io.seal := boundary.seal
        owner.io.endEpisode := boundary.endEpisode
        boundary.busy := postedBusy
        when(fallbackDrainActive.get) {
            assert(boundary.contextEpoch === fallbackDrainEpoch.get,
                "cache fallback context changed before real coherence drain")
        }
        boundary.episodeActive := owner.io.episodeActive
        assert(!owner.io.failed, "platform violated guaranteed posted RAM refill success")
        owner.io.acknowledged := 0.U.asTypeOf(owner.io.acknowledged)
        owner.io.acquireIssued := 0.U.asTypeOf(owner.io.acquireIssued)
        owner.io.refill.valid := false.B
        owner.io.refill.bits := 0.U.asTypeOf(owner.io.refill.bits)
        owner.io.install.ready := false.B
        owner.io.drained.ready := true.B
        owner.io.released.ready := true.B
        owner.io.writebackAttached := 0.U.asTypeOf(owner.io.writebackAttached)
        owner.io.writebackSent := 0.U.asTypeOf(owner.io.writebackSent)
        owner.io.writebackCompleted := 0.U.asTypeOf(owner.io.writebackCompleted)
        owner.io.victimCancelled := 0.U.asTypeOf(owner.io.victimCancelled)
        owner.io.fallback.ready := false.B
        owner.io.fallbackAcknowledged := 0.U.asTypeOf(owner.io.fallbackAcknowledged)
        val held = RegNext(io.upstream.request.valid && !io.upstream.request.ready, false.B)
        val proofPayload = Cat(boundary.requestProof.valid,
            Mux(boundary.requestProof.valid, boundary.requestProof.bits.asUInt, 0.U))
        val prior = RegEnable(Cat(io.upstream.request.bits.asUInt, proofPayload),
            io.upstream.request.valid && !io.upstream.request.ready)
        val heldProof = RegNext(postedIntent && !io.upstream.request.ready, false.B)
        val priorEpoch = RegEnable(boundary.contextEpoch, postedIntent && !io.upstream.request.ready)
        when(held) { assert(io.upstream.request.valid &&
            Cat(io.upstream.request.bits.asUInt, proofPayload) === prior,
            "cache held original request/proof changed") }
        when(heldProof) { assert(boundary.contextEpoch === priorEpoch &&
            boundary.requestProof.bits.epoch === priorEpoch, "cache held posted context changed") }
        when(postedIntent) {
            val proof = boundary.requestProof.bits
            assert(proof.epoch === boundary.contextEpoch && proof.address === io.upstream.request.bits.address &&
                proof.data === io.upstream.request.bits.data && proof.mask === io.upstream.request.bits.mask &&
                proof.size === io.upstream.request.bits.size, "cache original posted proof detached from request")
        }
        when(boundary.endEpisode) {
            assert(!postedIntent, "episode ended beside held or accepted original proof")
            assert(!postedBusy, "episode ended before accepted cache/fallback coherence drain")
        }
    }
    private val tagGeometry = tagConfig.geometry(base, bytes, 6 + setBits)
    private val valid = RegInit(VecInit(Seq.fill(lines)(false.B)))
    private val dirty = RegInit(VecInit(Seq.fill(lines)(false.B)))
    // The opt-in FPGA layout has one write port and two asynchronous read
    // ports per way. Valid/dirty/replacement remain resettable registers.
    private val tags = if (!tagConfig.bankedStorage) Some(Reg(Vec(lines, UInt(tagGeometry.tagBits.W)))) else None
    private val tagBanks = if (tagConfig.bankedStorage)
        Some(Seq.fill(ways)(Mem(lines / ways, UInt(tagGeometry.tagBits.W)))) else None
    private val primaryTagSet = WireDefault(io.upstream.request.bits.address(5 + setBits, 6))
    private val primaryTags = tagBanks.map(banks => VecInit(banks.map(_.read(primaryTagSet))))
    private val replacement = if (ways == 2) Some(RegInit(VecInit(Seq.fill(lines / ways)(false.B)))) else None
    private val data = Seq.fill(8)(SyncReadMem(lines, Vec(8, UInt(8.W))))

    private def lineSet(address: UInt): UInt = address(5 + setBits, 6)
    private def lineTag(address: UInt): UInt = tagGeometry.tag(address)
    private def slot(address: UInt, way: Int): UInt =
        if (ways == 1) lineSet(address) else Cat(way.U(1.W), lineSet(address))
    private def matches(address: UInt, way: Int): Bool =
        tagGeometry.qualifies(address) && valid(slot(address, way)) &&
            (if (tagConfig.bankedStorage) primaryTags.get(way) else tags.get(slot(address, way))) === lineTag(address)
    private def residentSlot(address: UInt): UInt =
        if (ways == 1) lineSet(address) else Mux(matches(address, 0), slot(address, 0), slot(address, 1))
    private def slotAddress(index: UInt): UInt =
        tagGeometry.widen(Cat(tags.get(index), index(setBits - 1, 0), 0.U(6.W)))
    private def wayTag(read: Vec[UInt], index: UInt): UInt =
        if (ways == 1) read(0) else read(index(indexBits - 1))
    private def taggedAddress(tag: UInt, index: UInt): UInt =
        tagGeometry.widen(Cat(tag, index(setBits - 1, 0), 0.U(6.W)))
    private def touch(index: UInt): Unit = replacement.foreach { r =>
        r(index(setBits - 1, 0)) := !index(indexBits - 1)
    }
    private def merge(oldWord: UInt, request: DataRequest): UInt = Cat((7 to 0 by -1).map { i =>
        Mux(request.mask(i), request.data(8 * i + 7, 8 * i), oldWord(8 * i + 7, 8 * i))
    })

    // A response credit is reserved before any SRAM or TL side effect. The
    // complete data lives here even after a probe invalidates its cache line.
    // 0 ordinary, 1 posted early response, 2 generation-exhausted legacy fallback.
    private val responseKind = postedConfig.map(_ => RegInit(VecInit(Seq.fill(responseCount)(0.U(2.W)))))
    private val responseMember = postedConfig.map(c => Reg(Vec(responseCount, new PostedStoreMember(c))))
    private val responseFallback = postedConfig.map(c => Reg(Vec(responseCount, new PostedFallbackAcknowledgement(c))))
    private val responseOwned = RegInit(VecInit(Seq.fill(responseCount)(false.B)))
    private val responseComplete = RegInit(VecInit(Seq.fill(responseCount)(false.B)))
    private val results = Reg(Vec(responseCount, new DataResponse))
    private val responseHead = RegInit(0.U(ticketBits.W))
    private val responseTail = RegInit(0.U(ticketBits.W))
    private val responseEmpty = !responseOwned.asUInt.orR
    private val responseSpace = !responseOwned(responseTail)
    private val hitReplyValid = WireDefault(false.B)
    private val hitReplyBits = WireDefault(0.U.asTypeOf(new DataResponse))
    private val storedReply = responseOwned(responseHead) && responseComplete(responseHead)
    io.upstream.response.valid := storedReply || hitReplyValid
    io.upstream.response.bits := Mux(storedReply, results(responseHead), hitReplyBits)
    when(io.upstream.response.fire) {
        responseOwned(responseHead) := false.B
        responseComplete(responseHead) := false.B
        responseHead := responseHead + 1.U
        for (owner <- posted) {
            owner.io.acknowledged.valid := responseKind.get(responseHead) === 1.U
            owner.io.acknowledged.bits := responseMember.get(responseHead)
            owner.io.fallbackAcknowledged.valid := responseKind.get(responseHead) === 2.U
            owner.io.fallbackAcknowledged.bits := responseFallback.get(responseHead)
            responseKind.get(responseHead) := 0.U
        }
    }

    private val free :: evictWait :: acquire :: fill :: result :: Nil = Enum(5)
    private val phase = RegInit(VecInit(Seq.fill(mshrCount)(free)))
    private val prefetchOwner = if (concurrency.nextLinePrefetch)
        RegInit(VecInit(Seq.fill(mshrCount)(false.B))) else WireDefault(VecInit(Seq.fill(mshrCount)(false.B)))
    private val storePrefetchOwner = if (concurrency.storeNextLinePrefetch)
        Some(RegInit(VecInit(Seq.fill(mshrCount)(false.B)))) else None
    // Wire breaks Scala declaration ordering; it carries actual pending refill,
    // not CPU VALID/READY, so it introduces no request-handshake feedback loop.
    private val prefetchRefillPending = WireDefault(false.B)
    io.prefetchBusy := false.B
    private val pending = Reg(Vec(mshrCount, new DataRequest))
    private val pendingIndex = Reg(Vec(mshrCount, UInt(indexBits.W)))
    // An accepted miss exclusively reserves its set. Capture its victim tag
    // once; a later probe may remove that victim but cannot replace the tag.
    private val pendingVictimTag = if (tagConfig.bankedStorage)
        Some(Reg(Vec(mshrCount, UInt(tagGeometry.tagBits.W)))) else None
    private val pendingTicket = Reg(Vec(mshrCount, UInt(ticketBits.W)))
    val mshrOccupancy = PopCount(phase.map(_ =/= free))
    private val mshrEmpty = mshrOccupancy === 0.U
    private val freeMask = VecInit(phase.map(_ === free))
    private val freeMshr = PriorityEncoder(freeMask)
    private val barrier = RegInit(false.B)
    private val barrierTicket = Reg(UInt(ticketBits.W))
    when(io.upstream.response.fire) {
        when(barrier && responseHead === barrierTicket) { barrier := false.B }
        for (i <- 0 until mshrCount) {
            when(phase(i) === result && !isPosted(i.U) && pendingTicket(i) === responseHead) { phase(i) := free }
        }
    }
    private val bIdle :: bEvict :: bSend :: bWait :: Nil = Enum(4)
    private val bypassState = RegInit(bIdle)
    private val bypassRequest = Reg(new DataRequest)
    private val bypassIndex = Reg(UInt(indexBits.W))
    private val bypassVictimTag = if (tagConfig.bankedStorage) Some(Reg(UInt(tagGeometry.tagBits.W))) else None
    private val bypassTicket = Reg(UInt(ticketBits.W))
    io.downstream.request.valid := bypassState === bSend
    io.downstream.request.bits := bypassRequest
    io.downstream.response.ready := bypassState === bWait
    when(io.downstream.request.fire) { bypassState := bWait }
    when(io.downstream.response.fire) {
        results(bypassTicket) := io.downstream.response.bits
        responseComplete(bypassTicket) := true.B
        bypassState := bIdle
    }

    private val flushActive = RegInit(false.B)
    private val flushFinished = RegInit(false.B)
    private val flushIndex = RegInit(0.U(indexBits.W))
    private val flushWaiting = RegInit(false.B)
    private val scanComplete = RegInit(false.B)
    if (tagConfig.bankedStorage) {
        // B has priority; demand cannot fire with BVALID and flush excludes
        // demand. Neither BREADY nor arbitration depends on the tag result.
        primaryTagSet := Mux(io.tl.b.fire, lineSet(io.tl.b.bits.address),
            Mux(flushActive, flushIndex(setBits - 1, 0), lineSet(io.upstream.request.bits.address)))
    }
    io.flushDone := flushFinished
    when(!io.flushRequest) { flushFinished := false.B }

    private val pIdle :: pCapture :: pSend :: Nil = Enum(3)
    private val probeState = RegInit(pIdle)
    private val probeAddress = Reg(UInt(64.W))
    private val probeSource = Reg(UInt(params.sourceBits.W))
    private val probeHit = Reg(Bool())
    private val probeDirty = Reg(Bool())
    private val probeWords = Reg(Vec(8, UInt(64.W)))
    private val probeBeat = RegInit(0.U(3.W))
    private val eIdle :: eCapture :: eSend :: eAck :: Nil = Enum(4)
    private val evictionState = RegInit(eIdle)
    private val ownerMiss :: ownerBypass :: ownerFlush :: Nil = Enum(3)
    private val evictionOwner = Reg(UInt(2.W))
    private val evictionMshr = Reg(UInt(mshrBits.W))
    private val evictionAddress = Reg(UInt(64.W))
    private val evictionDirty = Reg(Bool())
    private val evictionWords = Reg(Vec(8, UInt(64.W)))
    private val evictionBeat = RegInit(0.U(3.W))

    private val wbCount = concurrency.writebackEntries
    private val wbBits = math.max(1, log2Ceil(wbCount))
    private val wbPrefetch = if (concurrency.nextLinePrefetch && wbCount > 1)
        Some(RegInit(VecInit(Seq.fill(wbCount)(false.B)))) else None
    private val singleReleasePrefetch = if (concurrency.nextLinePrefetch && wbCount == 1)
        Some(RegInit(false.B)) else None
    private val wbLive = RegInit(VecInit(Seq.fill(wbCount)(false.B)))
    private val wbSent = RegInit(VecInit(Seq.fill(wbCount)(false.B)))
    private val wbOwner = Reg(Vec(wbCount, UInt(2.W)))
    private val wbMshr = Reg(Vec(wbCount, UInt(mshrBits.W)))
    private val wbAddress = Reg(Vec(wbCount, UInt(64.W)))
    private val wbSlot = Reg(UInt(wbBits.W))
    // Captured real WB lineage outlives response tickets; never infer it from wbMshr later.
    private val wbPosted = postedConfig.map(_ => RegInit(VecInit(Seq.fill(wbCount)(false.B))))
    private val wbPostedEvent = postedConfig.map(c => Reg(Vec(wbCount, new PostedWritebackEvent(c))))
    private val wbFree = PriorityEncoder(VecInit(wbLive.map(!_)))
    private val wbSpace = !wbLive.asUInt.andR
    private val wbEmpty = !wbLive.asUInt.orR
    private val ackIndex = (io.tl.d.bits.source - concurrency.releaseSource.U)(wbBits - 1, 0)
    private val ackInRange = io.tl.d.bits.source >= concurrency.releaseSource.U &&
        io.tl.d.bits.source < (concurrency.releaseSource + wbCount).U
    private val pendingMissWrite = VecInit((0 until mshrCount).map(i =>
        VecInit((0 until wbCount).map(j => wbLive(j) && (if (concurrency.overlapWritebackRefill) !wbSent(j) else true.B) && wbOwner(j) === ownerMiss && wbMshr(j) === i.U)).asUInt.orR))

    // The home may publish T ownership at E before the local result installs.
    // A B for that line waits for installation, independently of CPU DREADY.
    // A B for a dirty victim waits for its ReleaseAck, never replies N early.
    private val probeTransient = VecInit((0 until mshrCount).map(i =>
        phase(i) =/= free && pending(i).address(63, 6) === io.tl.b.bits.address(63, 6) &&
            (if (postedConfig.nonEmpty) Mux(isPosted(i.U), postedAcquired.get(i) && !postedInstalled.get(i),
                phase(i) =/= result) else phase(i) =/= result))).asUInt.orR
    private val probeEviction = evictionState =/= eIdle &&
        evictionAddress(63, 6) === io.tl.b.bits.address(63, 6) ||
        VecInit((0 until wbCount).map(i => wbLive(i) && wbAddress(i)(63, 6) === io.tl.b.bits.address(63, 6))).asUInt.orR
    io.tl.b.ready := probeState === pIdle && !probeTransient && !probeEviction
    private val probeFire = io.tl.b.fire
    private val probeIndex = residentSlot(io.tl.b.bits.address)
    private val actualProbeHit = (0 until ways).map(matches(io.tl.b.bits.address, _)).reduce(_ || _)
    private val probeRead = probeFire && actualProbeHit && dirty(probeIndex)
    when(probeFire) {
        assert(io.tl.b.bits.opcode === TLOpcode.ProbeBlock && io.tl.b.bits.size === 6.U &&
            io.tl.b.bits.param === TLPermissions.toN, "cache expects an invalidation probe")
        probeAddress := io.tl.b.bits.address
        probeSource := io.tl.b.bits.source
        probeHit := actualProbeHit
        probeDirty := actualProbeHit && dirty(probeIndex)
        when(actualProbeHit) { valid(probeIndex) := false.B; dirty(probeIndex) := false.B }
        probeState := pCapture
    }

    // Eviction requests own their set from CPU acceptance. A probe can remove
    // the victim before capture; then no redundant voluntary release is sent.
    // Retiring the old release permits registered capture of an already-known
    // next victim. No new C beat is offered combinationally from ReleaseAck.
    private val evictionRetiring = io.tl.d.fire && io.tl.d.bits.opcode === TLOpcode.ReleaseAck
    private val evictionLaneAvailable = if (wbCount == 1) evictionState === eIdle || evictionRetiring
        else evictionState === eIdle && wbSpace
    private val evictMask = VecInit((0 until mshrCount).map(i => phase(i) === evictWait && (if (wbCount > 1) !pendingMissWrite(i) else true.B) &&
        !((wbCount == 1).B && evictionRetiring && evictionOwner === ownerMiss && evictionMshr === i.U)))
    private val queuedEvictMshr = PriorityEncoder(evictMask)
    private val queuedMissEviction = evictMask.asUInt.orR
    private val evictFromBypass = bypassState === bEvict &&
        !VecInit((0 until wbCount).map(i => wbLive(i) && wbOwner(i) === ownerBypass)).asUInt.orR
    private val evictFromFlush = flushActive && !flushWaiting && !scanComplete &&
        valid(flushIndex) && dirty(flushIndex)
    private val queuedEvictWanted = queuedMissEviction || evictFromBypass || evictFromFlush
    private val queuedEvictIndex = Mux(queuedMissEviction, pendingIndex(queuedEvictMshr),
        Mux(evictFromBypass, bypassIndex, flushIndex))
    // A newly accepted miss can claim an otherwise idle victim lane directly.
    // Keep this separate from queued read-port arbitration: request.ready must
    // never depend on its own accepted direct-eviction read.
    private val directEviction = WireDefault(false.B)
    private val directEvictionIndex = WireDefault(0.U(indexBits.W))
    private val queuedEvictionRead = evictionLaneAvailable && queuedEvictWanted &&
        valid(queuedEvictIndex) && dirty(queuedEvictIndex) && !probeFire
    private val evictMshr = Mux(directEviction, freeMshr, queuedEvictMshr)
    private val evictFromMiss = queuedMissEviction || directEviction
    private val evictIndex = Mux(directEviction, directEvictionIndex, queuedEvictIndex)
    private val evictWanted = queuedEvictWanted || directEviction
    private val postedEvict = evictFromMiss && isPosted(evictMshr)
    private val startEviction = evictionLaneAvailable && evictWanted && valid(evictIndex) && !probeFire &&
        !(postedConfig.nonEmpty.B && (wbCount == 1).B && evictionRetiring)
    private val evictionRead = startEviction && dirty(evictIndex)
    private val evictAddress = if (tagConfig.bankedStorage) {
        val tag = Mux(directEviction, wayTag(primaryTags.get, evictIndex),
            Mux(queuedMissEviction, pendingVictimTag.get(queuedEvictMshr),
                Mux(evictFromBypass, bypassVictimTag.get, wayTag(primaryTags.get, evictIndex))))
        taggedAddress(tag, evictIndex)
    } else slotAddress(evictIndex)
    when(evictionLaneAvailable && !probeFire) {
        when(evictFromMiss && !valid(evictIndex)) {
            phase(evictMshr) := acquire
            for (owner <- posted) {
                when(isPosted(evictMshr)) {
                    owner.io.victimCancelled.valid := true.B
                    owner.io.victimCancelled.bits.context := postedContext.get(evictMshr)
                    owner.io.victimCancelled.bits.reservation := postedReservation.get(evictMshr)
                }
            }
        }
        when(!evictFromMiss && evictFromBypass && !valid(evictIndex)) { bypassState := bSend }
    }
    when((wbCount == 1).B && startEviction && evictionRetiring && evictionOwner === ownerMiss && evictFromMiss) {
        assert(evictMshr =/= evictionMshr, "victim turnover reselected retiring owner")
    }
    when(startEviction) {
        for (owner <- posted) {
            val captureSlot = if (wbCount == 1) 0.U else wbFree
            wbPosted.get(captureSlot) := postedEvict
            when(postedEvict) {
                val event = Wire(new PostedWritebackEvent(postedConfig.get))
                event.context := postedContext.get(evictMshr)
                event.reservation := postedReservation.get(evictMshr)
                event.ticket.slot := captureSlot
                event.ticket.owner := postedContext.get(evictMshr).owner
                wbPostedEvent.get(captureSlot) := event
                owner.io.writebackAttached.valid := true.B
                owner.io.writebackAttached.bits := event
                assert(evictAddress === event.reservation.victimAddress,
                    "posted capture changed its original victim address")
            }
        }
        // A free MSHR can still contain a previous PF bit. A newly admitted
        // direct demand eviction must never inherit that old WB lineage.
        val capturedPrefetch = evictFromMiss && prefetchOwner(evictMshr) &&
            (if (concurrency.storeNextLinePrefetch) !directEviction else true.B)
        wbPrefetch.foreach(_(wbFree) := capturedPrefetch)
        singleReleasePrefetch.foreach(_ := capturedPrefetch)
        if (wbCount > 1) {
            wbSlot := wbFree
            wbLive(wbFree) := true.B
            wbSent(wbFree) := false.B
            wbOwner(wbFree) := Mux(evictFromMiss, ownerMiss, Mux(evictFromBypass, ownerBypass, ownerFlush))
            wbMshr(wbFree) := evictMshr
            wbAddress(wbFree) := evictAddress
        }
        evictionOwner := Mux(evictFromMiss, ownerMiss, Mux(evictFromBypass, ownerBypass, ownerFlush))
        evictionMshr := evictMshr
        evictionAddress := evictAddress
        evictionDirty := dirty(evictIndex)
        valid(evictIndex) := false.B
        dirty(evictIndex) := false.B
        evictionState := eCapture
        when(!evictFromMiss && !evictFromBypass) { flushWaiting := true.B }
    }

    private val request = io.upstream.request.bits
    private val found = (0 until ways).map(matches(request.address, _)).reduce(_ || _)
    private val victim = if (ways == 1) lineSet(request.address) else {
        val first = slot(request.address, 0)
        val second = slot(request.address, 1)
        Mux(!valid(first), first, Mux(!valid(second), second,
            Cat(replacement.get(lineSet(request.address)), lineSet(request.address))))
    }
    private val index = Mux(found, residentSlot(request.address), victim)
    private val cacheable = request.address >= base.U(65.W) &&
        (request.address +& (1.U(64.W) << request.size)) <= (base + bytes).U(65.W)
    private val ordinary = cacheable && !request.atomic && !request.virtualized && !request.uncached
    private val bypass = !ordinary
    private val readHit = ordinary && found && !request.write
    private val writeHit = ordinary && found && request.write
    private val needsEviction = cacheable && valid(index) && (!found || bypass)
    private val reservedSet = VecInit((0 until mshrCount).map(i => phase(i) =/= free &&
        pendingIndex(i)(setBits - 1, 0) === lineSet(request.address))).asUInt.orR
    // Hits retain the legacy acceptance-ordered read/store pipeline. Store
    // misses and bypasses still fence; no store hit crosses live miss/maintenance.
    private val barrierRequest = bypass || (request.write && !writeHit)
    private val prefetchOnlyHit = if (concurrency.storeNextLinePrefetch) {
        val onlyPrefetchMisses = VecInit((0 until mshrCount).map(i =>
            phase(i) === free || prefetchOwner(i))).asUInt.andR
        val onlySentPrefetchWritebacks = wbPrefetch.map { saved =>
            VecInit((0 until wbCount).map(i => !wbLive(i) || (saved(i) && wbSent(i) &&
                lineSet(wbAddress(i)) =/= lineSet(request.address)))).asUInt.andR
        }.getOrElse(wbEmpty)
        onlyPrefetchMisses && onlySentPrefetchWritebacks && !prefetchRefillPending && !queuedEvictWanted
    } else false.B
    private val storeHitSafe = ((mshrEmpty && wbEmpty) || prefetchOnlyHit) &&
        evictionState === eIdle && probeState === pIdle && bypassState === bIdle
    private val barrierSafe = responseEmpty && mshrEmpty && wbEmpty && evictionState === eIdle &&
        probeState === pIdle && bypassState === bIdle
    private val needsMissSlot = ordinary && !found
    private val legacyReady = responseSpace && !barrier && !flushActive && !io.flushRequest &&
        !io.tl.b.valid && !reservedSet && (!barrierRequest || barrierSafe) &&
        (!writeHit || storeHitSafe) &&
        (!needsMissSlot || freeMask.asUInt.orR) && (!readHit || !queuedEvictionRead)
    io.upstream.request.ready := legacyReady
    for ((owner, boundary) <- posted.zip(io.posted)) {
        val legacyMshrsClear = VecInit((0 until mshrCount).map(i => phase(i) === free || isPosted(i.U))).asUInt.andR
        val legacyResponsesClear = VecInit((0 until responseCount).map(i =>
            !responseOwned(i) || responseKind.get(i) === 1.U)).asUInt.andR
        val legacyWbClear = if (wbCount == 1) evictionState === eIdle || wbPosted.get(0) else
            VecInit((0 until wbCount).map(i => !wbLive(i) || wbPosted.get(i))).asUInt.andR
        val legacyClear = legacyMshrsClear && legacyResponsesClear && legacyWbClear && !io.prefetchBusy &&
            bypassState === bIdle && (evictionState === eIdle ||
                (if (wbCount == 1) wbPosted.get(0) else wbPosted.get(wbSlot)))
        val maintenanceReady = legacyClear && !barrier && !flushActive && !io.flushRequest &&
            probeState === pIdle && !io.tl.b.valid
        owner.io.cacheAdmission.responseAvailable := responseSpace && maintenanceReady
        owner.io.cacheAdmission.targetAbsent := !found
        owner.io.cacheAdmission.responseTicket := responseTail
        owner.io.cacheAdmission.reservationValid := freeMask.asUInt.orR && !reservedSet && maintenanceReady
        owner.io.cacheAdmission.reservation.mshr := freeMshr
        owner.io.cacheAdmission.reservation.set := lineSet(request.address)
        owner.io.cacheAdmission.reservation.way := (if (ways == 1) 0.U else index(indexBits - 1))
        owner.io.cacheAdmission.reservation.victimValid := valid(index)
        owner.io.cacheAdmission.reservation.victimDirty := valid(index) && dirty(index)
        owner.io.cacheAdmission.reservation.victimAddress := (if (tagConfig.bankedStorage)
            taggedAddress(wayTag(primaryTags.get, index), index) else slotAddress(index))
        postedLegacyHit := owner.io.eligible && !owner.io.exhausted && writeHit
        val eligibleProof = boundary.requestProof.valid && owner.io.eligible
        val mergeRoute = eligibleProof && !owner.io.exhausted && !found
        val fallbackRoute = eligibleProof && owner.io.exhausted
        val commitReady = mergeRoute && owner.io.enq.ready
        // Only this bridge commits normal merges. The true held offer is upstream;
        // readiness uses pre-edge resources and no cpuFire/accepted/engine fire.
        owner.io.enq.valid := io.upstream.request.valid && (commitReady || fallbackRoute)
        // Coexistence makes PF/legacy windows reachable even after generation
        // exhaustion. A fallback hit must reserve the same complete legacy
        // response/maintenance boundary asserted by the owner on fallback.fire.
        owner.io.fallback.ready := legacyReady && !postedBusy &&
            (if (concurrency.postedPrefetchCoexistence) maintenanceReady else true.B)
        io.upstream.request.ready := Mux(mergeRoute, commitReady,
            Mux(fallbackRoute, owner.io.enq.ready, legacyReady && !postedBusy))
    }
    private val cpuFire = io.upstream.request.fire
    directEviction := cpuFire && !postedAccept && needsMissSlot && needsEviction &&
        evictionLaneAvailable && !queuedEvictWanted && probeState === pIdle &&
        !io.tl.b.valid && !flushActive && !io.flushRequest && bypassState === bIdle
    directEvictionIndex := index
    when(directEviction) {
        assert(phase(freeMshr) === free && !reservedSet && !probeFire,
            "direct victim allocation requires an admitted independent miss owner")
    }
    private val hitRead = cpuFire && !postedAccept && readHit
    private val storeWrite = cpuFire && !postedAccept && writeHit && !needsEviction
    private val hitPending = RegInit(false.B)
    private val hitTicket = Reg(UInt(ticketBits.W))
    private val hitBank = Reg(UInt(3.W))
    private val hitStore = Reg(Bool())
    hitPending := false.B
    when(cpuFire) {
        responseOwned(responseTail) := true.B
        responseComplete(responseTail) := postedAccept
        responseTail := responseTail + 1.U
        for (owner <- posted) {
            responseKind.get(responseTail) := Mux(postedAccept, 1.U, Mux(postedFallbackFire, 2.U, 0.U))
            when(postedAccept) {
                responseMember.get(responseTail) := owner.io.accepted.bits.member
                results(responseTail) := 0.U.asTypeOf(new DataResponse)
            }
            when(postedFallbackFire) {
                responseFallback.get(responseTail).token := owner.io.fallback.bits.proof.token
                responseFallback.get(responseTail).responseTicket := responseTail
            }
        }
        when(barrierRequest && !postedAccept) { barrier := true.B; barrierTicket := responseTail }
        when(postedAccept) {
            for (owner <- posted) {
                when(owner.io.accepted.bits.newLine) {
                    val m = owner.io.accepted.bits.reservation.mshr
                    postedMshr.get(m) := true.B
                    postedContext.get(m) := owner.io.accepted.bits.member.context
                    postedReservation.get(m) := owner.io.accepted.bits.reservation
                    postedAcquired.get(m) := false.B
                    postedInstalled.get(m) := false.B
                    if (concurrency.nextLinePrefetch) prefetchOwner(m) := false.B
                    storePrefetchOwner.foreach(_(m) := false.B)
                    pending(m) := request
                    pendingIndex(m) := index
                    pendingVictimTag.foreach(_(m) := wayTag(primaryTags.get, index))
                    phase(m) := Mux(needsEviction, evictWait, acquire)
                }
            }
        }.elsewhen(bypass) {
            bypassRequest := request
            bypassIndex := index
            bypassVictimTag.foreach(_ := wayTag(primaryTags.get, index))
            bypassTicket := responseTail
            bypassState := Mux(needsEviction, bEvict, bSend)
        }.elsewhen(found) {
            hitPending := true.B
            hitTicket := responseTail
            hitBank := request.address(5, 3)
            hitStore := request.write
            touch(index)
            when(request.write) { dirty(index) := true.B }
        }.otherwise {
            if (concurrency.nextLinePrefetch) prefetchOwner(freeMshr) := false.B
            storePrefetchOwner.foreach(_(freeMshr) := false.B)
            postedMshr.foreach(_(freeMshr) := false.B)
            pending(freeMshr) := request
            pendingIndex(freeMshr) := index
            pendingVictimTag.foreach(_(freeMshr) := wayTag(primaryTags.get, index))
            pendingTicket(freeMshr) := responseTail
            phase(freeMshr) := Mux(needsEviction, evictWait, acquire)
        }
    }

    private val readIndex = Mux(probeRead, probeIndex, Mux(evictionRead, evictIndex, index))
    private val readEnables = VecInit((0 until 8).map(bank => probeRead || evictionRead ||
        (hitRead && request.address(5, 3) === bank.U)))
    private val readWords = VecInit((0 until 8).map { bank =>
        data(bank).read(readIndex, readEnables(bank)).asUInt
    })
    hitReplyValid := hitPending && hitTicket === responseHead && responseOwned(responseHead) &&
        !responseComplete(responseHead)
    hitReplyBits.data := Mux(hitStore, 0.U, readWords(hitBank))
    hitReplyBits.error := false.B
    hitReplyBits.pageFault := false.B
    when(hitPending) {
        assert(responseOwned(hitTicket) && !responseComplete(hitTicket), "hit response lost its credit")
        results(hitTicket).data := Mux(hitStore, 0.U, readWords(hitBank))
        results(hitTicket).error := false.B
        results(hitTicket).pageFault := false.B
        when(!(hitReplyValid && io.upstream.response.fire)) { responseComplete(hitTicket) := true.B }
    }
    when(probeState === pCapture) {
        probeWords := Mux(probeDirty, readWords, 0.U.asTypeOf(probeWords))
        probeBeat := 0.U
        probeState := pSend
    }
    when(evictionState === eCapture) {
        evictionWords := Mux(evictionDirty, readWords, 0.U.asTypeOf(evictionWords))
        evictionBeat := 0.U
        evictionState := eSend
    }

    private val acquireTagBits = postedConfig.map(c => mshrBits + c.lineBits + c.generationBits + 2).getOrElse(mshrBits)
    private val engine = Module(new TileLinkLineAcquireEngine(params,
        entries = concurrency.acquireEntries, tagBits = acquireTagBits, observeIssued = postedConfig.nonEmpty))
    private def transactionTag(m: UInt): UInt = postedConfig.map { c =>
        val kind = Mux(isPosted(m), 2.U(2.W), Mux(prefetchOwner(m), 1.U(2.W), 0.U(2.W)))
        Cat(kind, Mux(isPosted(m), postedContext.get(m).owner.generation, 0.U(c.generationBits.W)),
            Mux(isPosted(m), postedContext.get(m).owner.slot, 0.U(c.lineBits.W)), m)
    }.getOrElse(m)
    private def tagMshr(tag: UInt): UInt = tag(mshrBits - 1, 0)
    private val acquireMask = VecInit(phase.map(_ === acquire))
    private val acquireMshr = PriorityEncoder(acquireMask)
    // AcquireEngine latches this candidate on request.fire and owns its A offer.
    engine.io.request.valid := acquireMask.asUInt.orR
    engine.io.request.bits.address := Cat(pending(acquireMshr).address(63, 6), 0.U(6.W))
    engine.io.request.bits.tag := transactionTag(acquireMshr)
    engine.io.request.bits.grow := TLPermissions.nToT
    engine.io.request.bits.permissionOnly := false.B
    when(engine.io.request.fire) { phase(acquireMshr) := fill }
    for (owner <- posted) {
        val issued = engine.io.issued.get
        val m = tagMshr(issued.bits)
        when(issued.valid) {
            assert(issued.bits === transactionTag(m) && phase(m) === fill,
                "actual A tag lost full transaction identity")
            when(isPosted(m)) {
                postedAcquired.get(m) := true.B
                owner.io.acquireIssued.valid := true.B
                owner.io.acquireIssued.bits.context := postedContext.get(m)
                owner.io.acquireIssued.bits.reservation := postedReservation.get(m)
            }
        }
    }
    private val fillMshr = tagMshr(engine.io.response.bits.tag)
    private val fillIndex = pendingIndex(fillMshr)
    private val fillRequest = pending(fillMshr)
    private val fillTicket = pendingTicket(fillMshr)
    // Reserved ledger storage guarantees that completed fills can always install.
    engine.io.response.ready := true.B
    private val postedFill = isPosted(fillMshr)
    for (owner <- posted) {
        owner.io.refill.valid := engine.io.response.valid && postedFill
        owner.io.refill.bits.context := postedContext.get(fillMshr)
        owner.io.refill.bits.reservation := postedReservation.get(fillMshr)
        owner.io.refill.bits.data := engine.io.response.bits.data
        owner.io.refill.bits.error := engine.io.response.bits.error
        owner.io.refill.bits.toT := engine.io.response.bits.cap === TLPermissions.toT
        owner.io.refill.bits.hasData := engine.io.response.bits.hasData
        // Engine exposes a completed response only after its real E.fire.
        owner.io.refill.bits.grantAcked := true.B
        engine.io.response.ready := Mux(postedFill, owner.io.refill.ready, true.B)
        when(engine.io.response.valid) {
            assert(engine.io.response.bits.tag === transactionTag(fillMshr),
                "returned acquire kind/full generation lost its original MSHR")
        }
    }
    private val refill = engine.io.response.fire && !postedFill
    private val postedInstall = posted.map(_.io.install.fire).getOrElse(false.B)
    private val postedInstallIndex = posted.map { owner =>
        val reservation = owner.io.install.bits.reservation
        if (ways == 1) reservation.set else Cat(reservation.way, reservation.set)
    }.getOrElse(0.U(indexBits.W))
    private val postedInstallAddress = posted.map(_.io.install.bits.context.lineAddress).getOrElse(0.U(64.W))
    private val postedInstallData = posted.map(_.io.install.bits.data).getOrElse(0.U(512.W))
    for (owner <- posted) {
        owner.io.install.ready := !refill && !storeWrite &&
            !(readEnables.asUInt.orR && readIndex === postedInstallIndex)
        when(owner.io.install.fire) {
            val m = owner.io.install.bits.reservation.mshr
            assert(isPosted(m) && phase(m) === fill && !postedInstalled.get(m) &&
                owner.io.install.bits.context.asUInt === postedContext.get(m).asUInt,
                "posted SRAM install lost its retained MSHR")
            postedInstalled.get(m) := true.B
            phase(m) := result
        }
        when(owner.io.released.fire) {
            val m = owner.io.released.bits.reservation.mshr
            assert(isPosted(m) && phase(m) === result && postedInstalled.get(m) &&
                owner.io.released.bits.context.asUInt === postedContext.get(m).asUInt,
                "posted release lost retained owner or installation")
            postedMshr.get(m) := false.B
            postedAcquired.get(m) := false.B
            postedInstalled.get(m) := false.B
            phase(m) := free
        }
    }
    prefetchRefillPending := engine.io.response.valid
    for (bank <- 0 until 8) {
        val oldWord = engine.io.response.bits.data(64 * bank + 63, 64 * bank)
        val word = Mux(fillRequest.write && fillRequest.address(5, 3) === bank.U,
            merge(oldWord, fillRequest), oldWord)
        val hitWrite = storeWrite && request.address(5, 3) === bank.U
        val lineWrite = (refill && !engine.io.response.bits.error) || postedInstall
        val writeIndex = Mux(postedInstall, postedInstallIndex, Mux(refill, fillIndex, index))
        val writeWord = Mux(postedInstall, postedInstallData(64 * bank + 63, 64 * bank),
            Mux(refill, word, request.data))
        when(readEnables(bank) && (lineWrite || hitWrite)) {
            assert(readIndex =/= writeIndex, "undefined same-address SRAM read/write collision")
        }
        when(lineWrite || hitWrite) {
            data(bank).write(writeIndex, writeWord.asTypeOf(Vec(8, UInt(8.W))),
                Mux(lineWrite, 255.U(8.W), request.mask).asBools)
        }
    }
    when(refill) {
        assert(phase(fillMshr) === fill && (prefetchOwner(fillMshr) ||
            (responseOwned(fillTicket) && !responseComplete(fillTicket))),
            "refill lost MSHR or response ownership")
        assert(!storeWrite, "barrier store overlapped a refill SRAM write")
        assert(prefetchOwner(fillMshr) || !hitPending || hitTicket =/= fillTicket, "hit and refill shared a response ticket")
        assert(engine.io.response.bits.cap === TLPermissions.toT || engine.io.response.bits.error,
            "write-back L1 requires T permission")

        when(!prefetchOwner(fillMshr)) {
        results(fillTicket).data := Mux(fillRequest.write || engine.io.response.bits.error, 0.U,
            (engine.io.response.bits.data >> (fillRequest.address(5, 3) << 6))(63, 0))
        results(fillTicket).error := engine.io.response.bits.error
        results(fillTicket).pageFault := false.B
        responseComplete(fillTicket) := true.B
        phase(fillMshr) := result
        }.otherwise { phase(fillMshr) := free }
    }
    private val installLine = (refill && !engine.io.response.bits.error) || postedInstall
    private val installIndex = Mux(postedInstall, postedInstallIndex, fillIndex)
    private val installAddress = Mux(postedInstall, postedInstallAddress, fillRequest.address)
    when(installLine) {
        if (tagConfig.compact) assert(tagGeometry.contains(installAddress), "tag install outside aperture")
        if (tagConfig.bankedStorage) {
            for (way <- 0 until ways) {
                when((ways == 1).B || installIndex(indexBits - 1) === way.U) {
                    tagBanks.get(way).write(installIndex(setBits - 1, 0), lineTag(installAddress))
                }
            }
        } else tags.get(installIndex) := lineTag(installAddress)
        valid(installIndex) := true.B
        dirty(installIndex) := postedInstall || fillRequest.write
        when(postedInstall || !prefetchOwner(fillMshr)) { touch(installIndex) }
        if (concurrency.nextLinePrefetch) {
            replacement.foreach { r => when(!postedInstall && prefetchOwner(fillMshr)) {
                r(fillIndex(setBits - 1, 0)) := (if (concurrency.storePrefetchMruInsertion)
                    Mux(storePrefetchOwner.get(fillMshr), !fillIndex(indexBits - 1), fillIndex(indexBits - 1))
                else fillIndex(indexBits - 1))
            } }
        }
    }
    if (concurrency.nextLinePrefetch) {
        val candidateValid = RegInit(false.B)
        val candidateAddress = Reg(UInt(64.W))
        val candidateStore = if (concurrency.storeNextLinePrefetch) Some(RegInit(false.B)) else None
        val observedTrackedStore = if (concurrency.storeNextLinePrefetch) Some(RegInit(false.B)) else None
        val candidateRemaining = if (concurrency.prefetchCandidateCycles > 1)
            Some(Reg(UInt(log2Ceil(concurrency.prefetchCandidateCycles).W))) else None
        val lastValid = RegInit(false.B)
        val lastLine = Reg(UInt(58.W))
        val trackedValid = RegInit(false.B)
        val trackedAddress = Reg(UInt(64.W))
        val trackedIndex = Reg(UInt(indexBits.W))
        val liveOwner = VecInit((0 until mshrCount).map(i => prefetchOwner(i) && phase(i) =/= free)).asUInt.orR
        // Release owner survives MSHR reuse; never infer it from wbMshr's
        // current prefetch bit after early writeback/refill overlap.
        val releaseBusy = wbPrefetch.map(v => VecInit((0 until wbCount).map(i =>
            wbLive(i) && v(i))).asUInt.orR).getOrElse(
            singleReleasePrefetch.map(_ && evictionState =/= eIdle).getOrElse(false.B))
        io.prefetchBusy := candidateValid || liveOwner || releaseBusy
        if (concurrency.postedPrefetchCoexistence) {
            // An old candidate cancels beside a held new-owner/fallback offer.
            // Its pre-edge busy bit still prevents that offer from allocating
            // a posted owner on this edge. Real PF/WB owners must drain in full.
            when(io.prefetch.candidate || io.prefetch.allocated) {
                assert(!postedBusy && (!postedIntent || postedLegacyHit),
                    "prefetch crossed posted work or a non-legacy proof offer")
                assert(!postedAccept && !postedFallbackFire,
                    "prefetch and posted responsibility began on the same edge")
            }
            when(postedAccept || postedFallbackFire) {
                assert(!candidateValid && !liveOwner && !releaseBusy,
                    "posted or fallback admission crossed accepted prefetch ownership")
            }
        }
        io.prefetch.missOwners := PopCount((0 until mshrCount).map(i => prefetchOwner(i) && phase(i) =/= free))
        io.prefetch.releaseOwners := wbPrefetch.map(v => PopCount((0 until wbCount).map(i => wbLive(i) && v(i))))
            .getOrElse(releaseBusy.asUInt)
        val consume = cpuFire && ordinary && trackedValid &&
            request.address(63, 6) === trackedAddress(63, 6)
        io.prefetch.useful := consume && (!request.write || concurrency.storeNextLinePrefetch.B)
        observationStorePrefetch.useful := io.prefetch.useful
        observationStorePrefetch.usefulStore := observedTrackedStore.getOrElse(false.B)
        io.prefetch.error := refill && prefetchOwner(fillMshr) && engine.io.response.bits.error
        val trackedPresent = if (tagConfig.bankedStorage) {
            // Every replacement invalidates its victim before tag installation.
            // The token sees that invalid cycle before any new tag can install,
            // so presence needs no third asynchronous tag read.
            valid(Mux(trackedValid, trackedIndex, 0.U))
        } else valid(Mux(trackedValid, trackedIndex, 0.U)) &&
            tags.get(Mux(trackedValid, trackedIndex, 0.U)) === lineTag(trackedAddress)
        when(trackedValid && (!trackedPresent || consume)) { trackedValid := false.B }
        // History predicts only; every token independently authorizes its new line.
        val line = request.address(63, 6)
        val sequential = lastValid && line === lastLine + 1.U && line =/= 0.U
        when(cpuFire && ordinary && !request.write) {
            lastValid := true.B
            lastLine := line
            when(sequential && request.prefetchNextAllowed && postedPrefetchAllowed &&
                !candidateValid && !liveOwner && !releaseBusy &&
                (!trackedValid || consume || !trackedPresent)) {
                io.prefetch.candidate := true.B
                candidateValid := true.B
                candidateAddress := Cat(request.address(63, 12), request.address(11, 6) + 1.U(6.W), 0.U(6.W))
                observationStorePrefetch.candidate := true.B
                observationStorePrefetch.candidateStore := false.B
                candidateStore.foreach(_ := false.B)
                candidateRemaining.foreach(_ := (concurrency.prefetchCandidateCycles - 1).U)
            }
        }
        if (concurrency.storeNextLinePrefetch) {
            val history = Module(new StorePrefetchHistory())
            history.io.acceptedStore := cpuFire && ordinary && request.write
            history.io.address := request.address
            history.io.currentlyAllowed := request.prefetchNextAllowed
            history.io.candidateAvailable := postedPrefetchAllowed && !candidateValid && !liveOwner && !releaseBusy &&
                (!trackedValid || consume || !trackedPresent)
            history.io.clear := io.flushRequest || (cpuFire && !ordinary)
            when(history.io.candidate) {
                io.prefetch.candidate := true.B
                candidateValid := true.B
                candidateAddress := Cat(request.address(63, 12), request.address(11, 6) + 1.U(6.W), 0.U(6.W))
                observationStorePrefetch.candidate := true.B
                observationStorePrefetch.candidateStore := true.B
                candidateStore.get := true.B
                candidateRemaining.foreach(_ := (concurrency.prefetchCandidateCycles - 1).U)
            }
        }
        if (concurrency.prefetchBreakOnStore) {
            // Admission ends the prior read stream even while this store's reply
            // is held. Merely offering a backpressured store changes no history.
            when(cpuFire && ordinary && request.write) { lastValid := false.B }
        }
        val candidateTags = tagBanks.map(banks => VecInit(banks.map(_.read(lineSet(candidateAddress)))))
        val present = (0 until ways).map { way =>
            tagGeometry.qualifies(candidateAddress) && valid(slot(candidateAddress, way)) &&
                (if (tagConfig.bankedStorage) candidateTags.get(way) else tags.get(slot(candidateAddress, way))) ===
                    lineTag(candidateAddress)
        }.reduce(_ || _)
        val first = slot(candidateAddress, 0)
        val pfIndex = if (ways == 1) first else {
            val second = slot(candidateAddress, 1)
            val dirtyChoice = if (concurrency.storeNextLinePrefetch)
                Mux(!dirty(second), second, Cat(replacement.get(lineSet(candidateAddress)), lineSet(candidateAddress)))
            else second
            Mux(!valid(first), first, Mux(!valid(second), second,
                Mux(!dirty(first), first, dirtyChoice)))
        }
        val setReserved = VecInit((0 until mshrCount).map(i => phase(i) =/= free &&
            pendingIndex(i)(setBits - 1, 0) === lineSet(candidateAddress))).asUInt.orR
        val victimPending = VecInit((0 until wbCount).map(i => wbLive(i) &&
            wbAddress(i)(63, 6) === candidateAddress(63, 6))).asUInt.orR
        val demandMiss = io.upstream.request.valid && ((needsMissSlot && !reservedSet) || barrierRequest || request.write)
        val otherwiseEligible = postedPrefetchAllowed && !liveOwner && !releaseBusy &&
            !present && !setReserved && !victimPending &&
            (!valid(pfIndex) || !dirty(pfIndex) || candidateStore.getOrElse(false.B)) &&
            freeMask.asUInt.orR && !demandMiss &&
            !barrier && !flushActive && !io.flushRequest && bypassState === bIdle &&
            probeState === pIdle && !io.tl.b.valid && !queuedEvictWanted
        val canAllocate = otherwiseEligible && evictionState === eIdle
        when(candidateValid) {
            candidateValid := false.B
            candidateRemaining.foreach { remaining =>
                // Retain only across the already-measured victim capture/send
                // hazard. All other demand/protection/ownership exclusions cancel
                // the token, and its existing busy contribution protects context.
                when(otherwiseEligible && (evictionState === eCapture || evictionState === eSend) &&
                    remaining =/= 0.U) {
                    candidateValid := true.B
                    remaining := remaining - 1.U
                }
            }
            when(canAllocate) {
                io.prefetch.allocated := true.B
                observationStorePrefetch.allocated := true.B
                observationStorePrefetch.allocatedStore := candidateStore.getOrElse(false.B)
                observationStorePrefetch.allocatedAddress := candidateAddress
                observationStorePrefetch.allocatedSlot := freeMshr
                observedTrackedStore.foreach(_ := candidateStore.get)
                assert(!cpuFire || !needsMissSlot, "prefetch stole an admitted demand slot")
                assert(candidateAddress >= base.U(65.W) &&
                    (candidateAddress +& 64.U(64.W)) <= (base + bytes).U(65.W), "prefetch escaped RAM")
                postedMshr.foreach(_(freeMshr) := false.B)
                pending(freeMshr) := 0.U.asTypeOf(new DataRequest)
                pending(freeMshr).address := candidateAddress
                pendingIndex(freeMshr) := pfIndex
                pendingVictimTag.foreach(_(freeMshr) := wayTag(candidateTags.get, pfIndex))
                pendingTicket(freeMshr) := 0.U
                prefetchOwner(freeMshr) := true.B
                storePrefetchOwner.foreach(_(freeMshr) := candidateStore.get)
                phase(freeMshr) := Mux(valid(pfIndex), evictWait, acquire)
            }
        }
        when(refill && prefetchOwner(fillMshr) && !engine.io.response.bits.error) {
            trackedValid := true.B
            trackedAddress := Cat(fillRequest.address(63, 6), 0.U(6.W))
            trackedIndex := fillIndex
        }
        when(io.flushRequest) { candidateValid := false.B; lastValid := false.B; trackedValid := false.B }
        // Direct eviction is a newly admitted demand using a FREE MSHR; its
        // previous prefetchOwner bit is stale until the allocation edge.
        when(startEviction && !directEviction && evictFromMiss && prefetchOwner(evictMshr)) {
            assert(!dirty(evictIndex) || storePrefetchOwner.map(_(evictMshr)).getOrElse(false.B),
                "dirty prefetch victim requires a captured store-origin owner")
        }
    }
    io.tl.a <> engine.io.a
    engine.io.d.valid := io.tl.d.valid && io.tl.d.bits.opcode =/= TLOpcode.ReleaseAck
    engine.io.d.bits := io.tl.d.bits
    io.tl.d.ready := Mux(io.tl.d.bits.opcode === TLOpcode.ReleaseAck,
        (if (wbCount == 1) evictionState === eAck else ackInRange && wbLive(ackIndex) && wbSent(ackIndex)), engine.io.d.ready)
    io.tl.e <> engine.io.e
    when(io.tl.d.fire && io.tl.d.bits.opcode === TLOpcode.ReleaseAck) {
        assert((if (wbCount == 1) evictionState === eAck && io.tl.d.bits.source === concurrency.releaseSource.U
            else ackInRange && wbLive(ackIndex) && wbSent(ackIndex)) &&
            !io.tl.d.bits.denied && !io.tl.d.bits.corrupt, "cache ReleaseAck owner/error mismatch")
        // All old-owner RHS values are the retiring registers. A simultaneous
        // next capture owns the lane state/metadata after this edge.
        if (wbCount == 1) { when(!startEviction) { evictionState := eIdle } }
        else { wbLive(ackIndex) := false.B; wbSent(ackIndex) := false.B }
        for (owner <- posted) {
            val retiringSlot = if (wbCount == 1) 0.U else ackIndex
            when(wbPosted.get(retiringSlot)) {
                owner.io.writebackCompleted.valid := true.B
                owner.io.writebackCompleted.bits := wbPostedEvent.get(retiringSlot)
                wbPosted.get(retiringSlot) := false.B
            }
        }
        val retiringOwner = if (wbCount == 1) evictionOwner else wbOwner(ackIndex)
        val retiringMshr = if (wbCount == 1) evictionMshr else wbMshr(ackIndex)
        when(retiringOwner === ownerMiss) {
            if (!concurrency.overlapWritebackRefill) phase(retiringMshr) := acquire
        }
            .elsewhen(retiringOwner === ownerBypass) { bypassState := bSend }
            .otherwise {
                if (!concurrency.overlapWritebackRefill) {
                    flushWaiting := false.B
                    when(flushIndex === (lines - 1).U) { scanComplete := true.B }
                        .otherwise { flushIndex := flushIndex + 1.U }
                }
            }
    }

    // Shared C has one irrevocable burst owner, including a stalled first beat.
    private val cLocked = RegInit(false.B)
    private val cOwnerProbe = Reg(Bool())
    private val selectProbe = Mux(cLocked, cOwnerProbe, probeState === pSend)
    io.tl.c.valid := Mux(selectProbe, probeState === pSend, evictionState === eSend)
    io.tl.c.bits := 0.U.asTypeOf(io.tl.c.bits)
    io.tl.c.bits.opcode := Mux(selectProbe,
        Mux(probeDirty, TLOpcode.ProbeAckData, TLOpcode.ProbeAck),
        Mux(evictionDirty, TLOpcode.ReleaseData, TLOpcode.Release))
    io.tl.c.bits.param := Mux(selectProbe, Mux(probeHit, TLPermissions.tToN, 5.U), TLPermissions.tToN)
    io.tl.c.bits.size := 6.U
    io.tl.c.bits.source := Mux(selectProbe, probeSource, concurrency.releaseSource.U + (if (wbCount == 1) 0.U else wbSlot))
    io.tl.c.bits.address := Mux(selectProbe, probeAddress, evictionAddress)
    io.tl.c.bits.data := Mux(selectProbe, probeWords(probeBeat), evictionWords(evictionBeat))
    private val cLast = Mux(selectProbe, !probeDirty || probeBeat === 7.U,
        !evictionDirty || evictionBeat === 7.U)
    when(io.tl.c.valid && !io.tl.c.ready) { cLocked := true.B; cOwnerProbe := selectProbe }
    when(io.tl.c.fire) {
        cLocked := !cLast
        cOwnerProbe := selectProbe
        when(selectProbe) {
            when(cLast) { probeState := pIdle }.otherwise { probeBeat := probeBeat + 1.U }
        }.otherwise {
            when(cLast) {
                for (owner <- posted) {
                    val sentSlot = if (wbCount == 1) 0.U else wbSlot
                    when(wbPosted.get(sentSlot)) {
                        owner.io.writebackSent.valid := true.B
                        owner.io.writebackSent.bits := wbPostedEvent.get(sentSlot)
                    }
                }
                if (wbCount == 1) evictionState := eAck
                else {
                    wbSent(wbSlot) := true.B; evictionState := eIdle
                    if (concurrency.overlapWritebackRefill) {
                        when(evictionOwner === ownerMiss) { phase(evictionMshr) := acquire }
                        when(evictionOwner === ownerFlush) {
                            // C completion transfers the complete victim to the home.
                            // Its later Ack owns only wbSlot, never this advancing scan.
                            flushWaiting := false.B
                            when(flushIndex === (lines - 1).U) { scanComplete := true.B }
                                .otherwise { flushIndex := flushIndex + 1.U }
                        }
                    }
                }
            }.otherwise { evictionBeat := evictionBeat + 1.U }
        }
    }

    for ((owner, boundary) <- posted.zip(io.posted)) {
        when(owner.io.fallback.fire) {
            fallbackDrainActive.get := true.B
            fallbackDrainEpoch.get := owner.io.fallback.bits.proof.epoch
        }
        // Only already accepted state appears here. A blocked new head/proof,
        // raw B/flush VALID or retained cohort identity cannot stop old drain.
        when(fallbackDrainActive.get && !owner.io.busy && responseEmpty && mshrEmpty &&
            wbEmpty && evictionState === eIdle && bypassState === bIdle && probeState === pIdle && !probeFire &&
            !io.prefetchBusy && !engine.io.response.valid && !engine.io.a.valid && !engine.io.e.valid) {
            fallbackDrainActive.get := false.B
        }
    }

    when(io.flushRequest && !flushFinished && !flushActive && !postedBusy && responseEmpty && mshrEmpty &&
        bypassState === bIdle && wbEmpty && evictionState === eIdle && probeState === pIdle && !io.tl.b.valid) {
        flushActive := true.B
        flushIndex := 0.U
        flushWaiting := false.B
        scanComplete := false.B
    }
    when(flushActive && !scanComplete && !flushWaiting && evictionState === eIdle &&
        probeState === pIdle && !io.tl.b.valid && (!valid(flushIndex) || !dirty(flushIndex))) {
        when(flushIndex === (lines - 1).U) { scanComplete := true.B }
            .otherwise { flushIndex := flushIndex + 1.U }
    }
    when(flushActive && scanComplete && wbEmpty && evictionState === eIdle && probeState === pIdle && !io.tl.b.valid) {
        flushActive := false.B
        flushFinished := true.B
    }

    observationLineWrite.valid := installLine
    observationLineWrite.posted := postedInstall
    observationLineWrite.address := Cat(installAddress(63, 6), 0.U(6.W))
    val ordinaryInstallWords = VecInit((0 until 8).map { bank =>
        val oldWord = engine.io.response.bits.data(64 * bank + 63, 64 * bank)
        Mux(fillRequest.write && fillRequest.address(5, 3) === bank.U, merge(oldWord, fillRequest), oldWord)
    })
    observationLineWrite.data := Mux(postedInstall, postedInstallData, ordinaryInstallWords.asUInt)
    for ((owner, observation) <- posted.zip(observationPosted)) {
        observation.accepted := owner.io.accepted
        observation.acknowledged := owner.io.acknowledged
        observation.acquired := owner.io.acquireIssued
        observation.refillValid := owner.io.refill.fire
        observation.refillEvent.context := owner.io.refill.bits.context
        observation.refillEvent.reservation := owner.io.refill.bits.reservation
        observation.refillData := owner.io.refill.bits.data
        observation.refillError := owner.io.refill.bits.error
        observation.installed.valid := owner.io.install.fire
        observation.installed.bits := owner.io.install.bits
        observation.drained.valid := owner.io.drained.fire
        observation.drained.bits := owner.io.drained.bits
        observation.released.valid := owner.io.released.fire
        observation.released.bits := owner.io.released.bits
        observation.attached := owner.io.writebackAttached
        observation.sent := owner.io.writebackSent
        observation.completed := owner.io.writebackCompleted
        observation.cancelled := owner.io.victimCancelled
        observation.fallback.valid := owner.io.fallback.fire
        observation.fallback.bits.token := owner.io.fallback.bits.proof.token
        observation.fallback.bits.responseTicket := responseTail
        observation.fallbackAck := owner.io.fallbackAcknowledged
        observation.failed := owner.io.failed
        observation.mshrMask := VecInit(phase.map(_ =/= free)).asUInt
        observation.postedMask := postedMshr.get.asUInt
        observation.responseMask := responseOwned.asUInt
        observation.responseCompleteMask := responseComplete.asUInt
        observation.wbMask := (if (wbCount == 1) (evictionState =/= eIdle).asUInt else wbLive.asUInt)
    }

    io.hit := cpuFire && ordinary && found
    io.miss := cpuFire && ordinary && !found
    io.profile.emptySlotMiss := io.miss && !valid(index)
    io.profile.replacementMiss := io.miss && valid(index)
    io.profile.readMiss := io.miss && !request.write
    io.profile.writeMiss := io.miss && request.write
    io.profile.dirtyEviction := startEviction && dirty(evictIndex) && (evictFromMiss || evictFromBypass)
    io.profile.missBlocked := io.upstream.request.valid && !io.upstream.request.ready && !mshrEmpty
    io.profile.bypassBlocked := io.upstream.request.valid && !io.upstream.request.ready && bypassState =/= bIdle
    io.profile.probeBlocked := io.upstream.request.valid && !io.upstream.request.ready &&
        (io.tl.b.valid || probeState =/= pIdle)
    io.profile.evictionCycle := evictionState =/= eIdle
    io.profile.refillCycle := phase.map(p => p === acquire || p === fill).reduce(_ || _)
    for (i <- 0 until mshrCount; j <- 0 until i) {
        assert(phase(i) === free || phase(j) === free ||
            pendingIndex(i)(setBits - 1, 0) =/= pendingIndex(j)(setBits - 1, 0), "two MSHRs reserved one set")
    }
    assert(!barrier || PopCount(responseOwned) === 1.U, "barrier overlapped another CPU request")
    when(storeWrite) {
        assert(ordinary && found && !request.atomic && !request.virtualized && !request.uncached && storeHitSafe,
            "store-hit pipeline crossed speculative/miss/bypass/maintenance ownership")
    }
    assert(!hitPending || responseOwned(hitTicket), "SRAM hit lost response credit")
    assert(PopCount(Seq(hitPending && !hitStore, probeState === pCapture && probeDirty,
        evictionState === eCapture && evictionDirty)) <= 1.U,
        "SRAM read result has more than one owner")
    // Passive reconstructed gate observations. No protocol/permission decision consumes them.
    observationStorePrefetch.demandAlloc := cpuFire && needsMissSlot
    observationStorePrefetch.demandAllocSlot := freeMshr
    observationStorePrefetch.demandAllocAddress := request.address
    observationStorePrefetch.mshrLiveMask := VecInit(phase.map(_ =/= free)).asUInt
    observationStorePrefetch.mshrPrefetchMask := prefetchOwner.asUInt
    observationStorePrefetch.mshrStoreMask := storePrefetchOwner.map(_.asUInt).getOrElse(0.U)
    observationStorePrefetch.refill := refill
    observationStorePrefetch.refillSlot := fillMshr
    observationStorePrefetch.refillAddress := fillRequest.address
    observationStorePrefetch.refillPrefetch := prefetchOwner(fillMshr)
    observationStorePrefetch.refillError := engine.io.response.bits.error
    observationStorePrefetch.wbCapture := startEviction
    observationStorePrefetch.wbCaptureSlot := wbFree
    observationStorePrefetch.wbCaptureMshr := evictMshr
    observationStorePrefetch.wbCaptureAddress := evictAddress
    observationStorePrefetch.wbCaptureDirty := dirty(evictIndex)
    observationStorePrefetch.wbCaptureDirect := directEviction
    observationStorePrefetch.wbCaptureFromMiss := evictFromMiss
    observationStorePrefetch.wbCapturePrefetch := evictFromMiss && prefetchOwner(evictMshr) &&
        (if (concurrency.storeNextLinePrefetch) !directEviction else true.B)
    observationStorePrefetch.wbLiveMask := wbLive.asUInt
    observationStorePrefetch.wbSentMask := wbSent.asUInt
    observationStorePrefetch.wbPrefetchMask := wbPrefetch.map(_.asUInt)
        .getOrElse(singleReleasePrefetch.getOrElse(false.B).asUInt)
    observationStorePrefetch.wbAddress0 := wbAddress(0)
    observationStorePrefetch.wbAddress1 := (if (wbCount > 1) wbAddress(1) else 0.U)
    observationStorePrefetch.wbMshr0 := wbMshr(0)
    observationStorePrefetch.wbMshr1 := (if (wbCount > 1) wbMshr(1) else 0.U)
    observationStorePrefetch.acquireResponsePending := engine.io.response.valid
    observationStorePrefetch.queuedEvictWanted := queuedEvictWanted
    observationStorePrefetch.responseFull := !responseSpace
    observationStorePrefetch.cValid := io.tl.c.valid
    observationStorePrefetch.cReady := io.tl.c.ready
    observationStorePrefetch.cOpcode := io.tl.c.bits.opcode
    observationStorePrefetch.cParam := io.tl.c.bits.param
    observationStorePrefetch.cSize := io.tl.c.bits.size
    observationStorePrefetch.cData := io.tl.c.bits.data
    observationStorePrefetch.dData := io.tl.d.bits.data
    observationStorePrefetch.dDenied := io.tl.d.bits.denied
    observationStorePrefetch.dCorrupt := io.tl.d.bits.corrupt

}
