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
    tagConfig: CacheTagConfig = CacheTagConfig.FullWidth
) extends CoherentLineCacheModule(params) {
    require(Set(2, 4).contains(concurrency.readMshrs))
    require(lines >= 4 && lines <= 512 && isPow2(lines))
    require(Set(1, 2).contains(ways) && lines / ways >= 2)
    require(bytes >= lines * 64 && bytes % 64 == 0 && base % 64 == 0)
    require(params.addrWidth == 64 && params.dataWidth == 64 &&
        params.sourceBits >= concurrency.sourceBits && params.sinkBits >= concurrency.sinkBits)
    private val mshrCount = concurrency.readMshrs
    require(lines / ways >= mshrCount, "each read MSHR needs an independently reservable set")
    private val mshrBits = log2Ceil(mshrCount)
    private val responseCount = concurrency.responseEntries
    private val ticketBits = log2Ceil(responseCount)
    private val indexBits = log2Ceil(lines)
    private val setBits = log2Ceil(lines / ways)
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
    }

    private val free :: evictWait :: acquire :: fill :: result :: Nil = Enum(5)
    private val phase = RegInit(VecInit(Seq.fill(mshrCount)(free)))
    private val prefetchOwner = if (concurrency.nextLinePrefetch)
        RegInit(VecInit(Seq.fill(mshrCount)(false.B))) else WireDefault(VecInit(Seq.fill(mshrCount)(false.B)))
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
            when(phase(i) === result && pendingTicket(i) === responseHead) { phase(i) := free }
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
        phase(i) =/= free && phase(i) =/= result &&
            pending(i).address(63, 6) === io.tl.b.bits.address(63, 6))).asUInt.orR
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
    private val startEviction = evictionLaneAvailable && evictWanted && valid(evictIndex) && !probeFire
    private val evictionRead = startEviction && dirty(evictIndex)
    private val evictAddress = if (tagConfig.bankedStorage) {
        val tag = Mux(directEviction, wayTag(primaryTags.get, evictIndex),
            Mux(queuedMissEviction, pendingVictimTag.get(queuedEvictMshr),
                Mux(evictFromBypass, bypassVictimTag.get, wayTag(primaryTags.get, evictIndex))))
        taggedAddress(tag, evictIndex)
    } else slotAddress(evictIndex)
    when(evictionLaneAvailable && !probeFire) {
        when(evictFromMiss && !valid(evictIndex)) { phase(evictMshr) := acquire }
        when(!evictFromMiss && evictFromBypass && !valid(evictIndex)) { bypassState := bSend }
    }
    when((wbCount == 1).B && startEviction && evictionRetiring && evictionOwner === ownerMiss && evictFromMiss) {
        assert(evictMshr =/= evictionMshr, "victim turnover reselected retiring owner")
    }
    when(startEviction) {
        wbPrefetch.foreach(_(wbFree) := evictFromMiss && prefetchOwner(evictMshr))
        singleReleasePrefetch.foreach(_ := evictFromMiss && prefetchOwner(evictMshr))
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
    private val storeHitSafe = mshrEmpty && wbEmpty && evictionState === eIdle && probeState === pIdle &&
        bypassState === bIdle
    private val barrierSafe = responseEmpty && mshrEmpty && wbEmpty && evictionState === eIdle &&
        probeState === pIdle && bypassState === bIdle
    private val needsMissSlot = ordinary && !found
    io.upstream.request.ready := responseSpace && !barrier && !flushActive && !io.flushRequest &&
        !io.tl.b.valid && !reservedSet && (!barrierRequest || barrierSafe) &&
        (!writeHit || storeHitSafe) &&
        (!needsMissSlot || freeMask.asUInt.orR) && (!readHit || !queuedEvictionRead)
    private val cpuFire = io.upstream.request.fire
    directEviction := cpuFire && needsMissSlot && needsEviction &&
        evictionLaneAvailable && !queuedEvictWanted && probeState === pIdle &&
        !io.tl.b.valid && !flushActive && !io.flushRequest && bypassState === bIdle
    directEvictionIndex := index
    when(directEviction) {
        assert(phase(freeMshr) === free && !reservedSet && !probeFire,
            "direct victim allocation requires an admitted independent miss owner")
    }
    private val hitRead = cpuFire && readHit
    private val storeWrite = cpuFire && writeHit && !needsEviction
    private val hitPending = RegInit(false.B)
    private val hitTicket = Reg(UInt(ticketBits.W))
    private val hitBank = Reg(UInt(3.W))
    private val hitStore = Reg(Bool())
    hitPending := false.B
    when(cpuFire) {
        responseOwned(responseTail) := true.B
        responseComplete(responseTail) := false.B
        responseTail := responseTail + 1.U
        when(barrierRequest) { barrier := true.B; barrierTicket := responseTail }
        when(bypass) {
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

    private val engine = Module(new TileLinkLineAcquireEngine(params,
        entries = concurrency.acquireEntries, tagBits = mshrBits))
    private val acquireMask = VecInit(phase.map(_ === acquire))
    private val acquireMshr = PriorityEncoder(acquireMask)
    // AcquireEngine latches this candidate on request.fire and owns its A offer.
    engine.io.request.valid := acquireMask.asUInt.orR
    engine.io.request.bits.address := Cat(pending(acquireMshr).address(63, 6), 0.U(6.W))
    engine.io.request.bits.tag := acquireMshr
    engine.io.request.bits.grow := TLPermissions.nToT
    engine.io.request.bits.permissionOnly := false.B
    when(engine.io.request.fire) { phase(acquireMshr) := fill }
    private val fillMshr = engine.io.response.bits.tag
    private val fillIndex = pendingIndex(fillMshr)
    private val fillRequest = pending(fillMshr)
    private val fillTicket = pendingTicket(fillMshr)
    // Reserved ledger storage guarantees that completed fills can always install.
    engine.io.response.ready := true.B
    private val refill = engine.io.response.fire
    for (bank <- 0 until 8) {
        val oldWord = engine.io.response.bits.data(64 * bank + 63, 64 * bank)
        val word = Mux(fillRequest.write && fillRequest.address(5, 3) === bank.U,
            merge(oldWord, fillRequest), oldWord)
        val hitWrite = storeWrite && request.address(5, 3) === bank.U
        when(readEnables(bank) && ((refill && !engine.io.response.bits.error) || hitWrite)) {
            assert(readIndex =/= Mux(refill, fillIndex, index), "undefined same-address SRAM read/write collision")
        }
        when((refill && !engine.io.response.bits.error) || hitWrite) {
            data(bank).write(Mux(refill, fillIndex, index),
                Mux(refill, word, request.data).asTypeOf(Vec(8, UInt(8.W))),
                Mux(refill, 255.U(8.W), request.mask).asBools)
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
        when(!engine.io.response.bits.error) {
            if (tagConfig.compact) assert(tagGeometry.contains(fillRequest.address), "tag install outside aperture")
            if (tagConfig.bankedStorage) {
                for (way <- 0 until ways) {
                    when((ways == 1).B || fillIndex(indexBits - 1) === way.U) {
                        tagBanks.get(way).write(fillIndex(setBits - 1, 0), lineTag(fillRequest.address))
                    }
                }
            } else tags.get(fillIndex) := lineTag(fillRequest.address)
            valid(fillIndex) := true.B
            dirty(fillIndex) := fillRequest.write
            when(!prefetchOwner(fillMshr)) { touch(fillIndex) }
            if (concurrency.nextLinePrefetch) {
                // Speculative fill enters at LRU; demand hits promote normally.
                replacement.foreach { r => when(prefetchOwner(fillMshr)) {
                    r(fillIndex(setBits - 1, 0)) := fillIndex(indexBits - 1)
                } }
            }
        }
        when(!prefetchOwner(fillMshr)) {
        results(fillTicket).data := Mux(fillRequest.write || engine.io.response.bits.error, 0.U,
            (engine.io.response.bits.data >> (fillRequest.address(5, 3) << 6))(63, 0))
        results(fillTicket).error := engine.io.response.bits.error
        results(fillTicket).pageFault := false.B
        responseComplete(fillTicket) := true.B
        phase(fillMshr) := result
        }.otherwise { phase(fillMshr) := free }
    }
    if (concurrency.nextLinePrefetch) {
        val candidateValid = RegInit(false.B)
        val candidateAddress = Reg(UInt(64.W))
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
        io.prefetch.missOwners := PopCount((0 until mshrCount).map(i => prefetchOwner(i) && phase(i) =/= free))
        io.prefetch.releaseOwners := wbPrefetch.map(v => PopCount((0 until wbCount).map(i => wbLive(i) && v(i))))
            .getOrElse(releaseBusy.asUInt)
        val consume = cpuFire && ordinary && trackedValid &&
            request.address(63, 6) === trackedAddress(63, 6)
        io.prefetch.useful := consume && !request.write
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
            when(sequential && request.prefetchNextAllowed && !candidateValid && !liveOwner && !releaseBusy &&
                (!trackedValid || consume || !trackedPresent)) {
                io.prefetch.candidate := true.B
                candidateValid := true.B
                candidateAddress := Cat(request.address(63, 12), request.address(11, 6) + 1.U(6.W), 0.U(6.W))
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
            Mux(!valid(first), first, Mux(!valid(second), second,
                Mux(!dirty(first), first, second)))
        }
        val setReserved = VecInit((0 until mshrCount).map(i => phase(i) =/= free &&
            pendingIndex(i)(setBits - 1, 0) === lineSet(candidateAddress))).asUInt.orR
        val victimPending = VecInit((0 until wbCount).map(i => wbLive(i) &&
            wbAddress(i)(63, 6) === candidateAddress(63, 6))).asUInt.orR
        val demandMiss = io.upstream.request.valid && ((needsMissSlot && !reservedSet) || barrierRequest || request.write)
        val otherwiseEligible = !liveOwner && !releaseBusy && !present && !setReserved && !victimPending &&
            (!valid(pfIndex) || !dirty(pfIndex)) && freeMask.asUInt.orR && !demandMiss &&
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
                assert(!cpuFire || !needsMissSlot, "prefetch stole an admitted demand slot")
                assert(candidateAddress >= base.U(65.W) &&
                    (candidateAddress +& 64.U(64.W)) <= (base + bytes).U(65.W), "prefetch escaped RAM")
                pending(freeMshr) := 0.U.asTypeOf(new DataRequest)
                pending(freeMshr).address := candidateAddress
                pendingIndex(freeMshr) := pfIndex
                pendingVictimTag.foreach(_(freeMshr) := wayTag(candidateTags.get, pfIndex))
                pendingTicket(freeMshr) := 0.U
                prefetchOwner(freeMshr) := true.B
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
            assert(!dirty(evictIndex), "prefetch must never generate dirty victim writeback")
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

    when(io.flushRequest && !flushFinished && !flushActive && responseEmpty && mshrEmpty &&
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
}
