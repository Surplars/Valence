package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLBundle, TLOpcode, TLParams, TLPermissions}
import soc.ip.tilelink.TileLinkLineAcquireEngine

class CoherentCacheProfile extends Bundle {
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
class CoherentLineCache(
    base: BigInt = BigInt("80010000", 16), bytes: BigInt = 8192, lines: Int = 128,
    params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
    ways: Int = 1, responseEntries: Int = 2, tagConfig: CacheTagConfig = CacheTagConfig.FullWidth
) extends CoherentLineCacheModule(params) {
    require(responseEntries >= 2 && responseEntries <= 16 && isPow2(responseEntries))
    require(lines >= 2 && lines <= 512 && isPow2(lines))
    require(Set(1, 2).contains(ways) && lines / ways >= 2)
    require(bytes >= 64 && bytes % 64 == 0 && base % 64 == 0)
    private val indexBits = log2Ceil(lines)
    private val setBits = log2Ceil(lines / ways)
    private val tagGeometry = tagConfig.geometry(base, bytes, 6 + setBits)
    private val Seq(idle, evictCapture, evictSend, evictAck, acquire, fill, missResponse,
        bypassSend, bypassResponse, probeCapture, probeSend, flushScan) = Enum(12)
    private val state = RegInit(idle)
    private val valid = RegInit(VecInit(Seq.fill(lines)(false.B)))
    private val dirty = RegInit(VecInit(Seq.fill(lines)(false.B)))
    private val tags = Reg(Vec(lines, UInt(tagGeometry.tagBits.W)))
    private val replacement = if (ways == 2)
        Some(RegInit(VecInit(Seq.fill(lines / ways)(false.B)))) else None
    private val data = Seq.fill(8)(SyncReadMem(lines, Vec(8, UInt(8.W))))
    private val pending = Reg(new DataRequest)
    private val pendingIndex = Reg(UInt(indexBits.W))
    private val pendingBypass = Reg(Bool())
    private val missResult = Reg(new DataResponse)
    private val victimAddress = Reg(UInt(64.W))
    private val victimDirty = Reg(Bool())
    private val victimWords = Reg(Vec(8, UInt(64.W)))
    private val releaseBeat = RegInit(0.U(3.W))
    private val probeAddress = Reg(UInt(params.addrWidth.W))
    private val probeSource = Reg(UInt(params.sourceBits.W))
    private val probeHit = Reg(Bool())
    private val probeDirty = Reg(Bool())
    private val probeWords = Reg(Vec(8, UInt(64.W)))
    private val probeBeat = RegInit(0.U(3.W))
    private val probeResume = Reg(UInt(state.getWidth.W))
    private val refillResultPending = WireDefault(false.B)
    private val flushActive = RegInit(false.B)
    private val flushFinished = RegInit(false.B)
    private val flushIndex = RegInit(0.U(indexBits.W))
    private val hitBank = Reg(UInt(3.W))
    private val readPending = RegInit(false.B)
    private val storePending = RegInit(false.B)
    private val readResponses = Module(new Queue(new DataResponse, responseEntries, pipe = false, flow = true))

    private def lineSet(address: UInt): UInt = address(5 + setBits, 6)
    private def lineTag(address: UInt): UInt = tagGeometry.tag(address)
    private def slot(address: UInt, way: Int): UInt =
        if (ways == 1) lineSet(address) else Cat(way.U(1.W), lineSet(address))
    private def matches(address: UInt, way: Int): Bool =
        tagGeometry.qualifies(address) && valid(slot(address, way)) && tags(slot(address, way)) === lineTag(address)
    private def residentSlot(address: UInt): UInt =
        if (ways == 1) lineSet(address) else Mux(matches(address, 0), slot(address, 0), slot(address, 1))
    private def slotAddress(index: UInt): UInt = tagGeometry.widen(Cat(tags(index), index(setBits - 1, 0), 0.U(6.W)))
    private def touch(index: UInt): Unit = replacement.foreach { lru =>
        lru(index(setBits - 1, 0)) := !index(indexBits - 1)
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
    private val cacheable = if (isPow2(bytes) && base % bytes == 0) {
        // An aligned power-of-two window needs neither a 65-bit end addition
        // nor wide magnitude comparisons on the request-to-SRAM-enable path.
        val offsetBits = log2Ceil(bytes)
        val maximumStart = MuxLookup(request.size, 0.U(offsetBits.W))(
            (0 to 3).map(s => s.U -> (bytes - (1 << s)).U(offsetBits.W)))
        request.address(63, offsetBits) === (base >> offsetBits).U((64 - offsetBits).W) &&
            request.address(offsetBits - 1, 0) <= maximumStart
    } else {
        request.address >= base.U(65.W) &&
            (request.address +& (1.U(64.W) << request.size)) <= (base + bytes).U(65.W)
    }
    private val ordinary = cacheable && !request.atomic && !request.virtualized && !request.uncached
    private val bypass = !ordinary
    private val needsEviction = cacheable && valid(index) && (!found || bypass)
    private val readHit = ordinary && found && !request.write
    private val writeHit = ordinary && found && request.write
    private val readCapacity = readResponses.io.count +& readPending.asUInt < responseEntries.U
    private val noReadOutstanding = readResponses.io.count === 0.U && !readPending
    private val cpuFire = io.upstream.request.fire
    private val cpuRead = cpuFire && ordinary && found
    private val evictRead = cpuFire && needsEviction
    private val probeRead = io.tl.b.fire
    private val flushRead = state === flushScan && !io.tl.b.valid && valid(flushIndex) && dirty(flushIndex)
    private val readWords = VecInit((0 until 8).map { i =>
        val enabled = probeRead || evictRead || flushRead || (cpuRead && request.address(5, 3) === i.U)
        data(i).read(Mux(probeRead, residentSlot(io.tl.b.bits.address),
            Mux(flushRead, flushIndex, index)), enabled).asUInt
    })
    private def merge(oldWord: UInt, write: DataRequest): UInt = Cat((7 to 0 by -1).map { i =>
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
    io.tl.b.ready := state === idle || state === acquire ||
        (state === fill && !refillResultPending) || state === missResponse ||
        state === bypassSend || state === bypassResponse || state === flushScan
    private val probing = state === probeCapture || state === probeSend
    private val bypassReply = state === bypassResponse || (probing && probeResume === bypassResponse)
    private val missReply = state === missResponse || (probing && probeResume === missResponse)
    private val queuedReply = state === idle || (probing && probeResume === idle)
    val hitUnderMiss = (state === acquire || state === fill) && readHit &&
        index =/= pendingIndex && readCapacity
    io.upstream.request.ready := !io.tl.b.valid && !io.flushRequest &&
        Mux(state === idle, Mux(readHit || writeHit, readCapacity,
            noReadOutstanding && Mux(bypass && !needsEviction, io.downstream.request.ready, true.B)),
            hitUnderMiss)
    io.downstream.request.valid := (state === bypassSend && !io.tl.b.valid) ||
        (state === idle && noReadOutstanding && io.upstream.request.valid && bypass && !io.flushRequest &&
            !needsEviction && !io.tl.b.valid)
    io.downstream.request.bits := Mux(state === bypassSend, pending, request)
    io.downstream.response.ready := bypassReply && io.upstream.response.ready
    readResponses.io.enq.valid := readPending
    readResponses.io.enq.bits.data := Mux(storePending, 0.U,
        Mux1H(UIntToOH(hitBank, 8), readWords))
    readResponses.io.enq.bits.error := false.B
    readResponses.io.enq.bits.pageFault := false.B
    readResponses.io.deq.ready := io.upstream.response.ready && queuedReply
    assert(!readPending || readResponses.io.enq.ready, "cache hit response queue overflow")
    // Probes must not withdraw an already offered CPU response. Keep the older
    // reply live under B/C backpressure; queued hit replies stay behind a miss.
    io.upstream.response.valid := (queuedReply && readResponses.io.deq.valid) || missReply ||
        (bypassReply && io.downstream.response.valid)
    io.upstream.response.bits := Mux(missReply, missResult,
        Mux(bypassReply, io.downstream.response.bits, readResponses.io.deq.bits))
    io.hit := cpuFire && ordinary && found
    io.miss := cpuFire && ordinary && !found
    io.profile.emptySlotMiss := io.miss && !valid(index)
    io.profile.replacementMiss := io.miss && valid(index)
    io.profile.readMiss := io.miss && !request.write
    io.profile.writeMiss := io.miss && request.write
    io.profile.dirtyEviction := cpuFire && needsEviction && dirty(index)
    io.profile.missBlocked := io.upstream.request.valid && !io.upstream.request.ready &&
        (state === evictCapture || state === evictSend || state === evictAck ||
            state === acquire || state === fill || state === missResponse)
    io.profile.bypassBlocked := io.upstream.request.valid && !io.upstream.request.ready &&
        (state === bypassSend || state === bypassResponse)
    io.profile.probeBlocked := io.upstream.request.valid && !io.upstream.request.ready &&
        (state === probeCapture || state === probeSend || (state === idle && io.tl.b.valid))
    io.profile.evictionCycle := state === evictCapture || state === evictSend || state === evictAck
    io.profile.refillCycle := state === acquire || state === fill
    readPending := false.B
    storePending := false.B
    when(!io.flushRequest) { flushFinished := false.B }
    when(state === idle && io.flushRequest && !flushFinished && noReadOutstanding && !io.tl.b.valid) {
        flushActive := true.B
        flushIndex := 0.U
        state := flushScan
    }
    when(state === flushScan && !io.tl.b.valid) {
        when(valid(flushIndex) && dirty(flushIndex)) {
            victimAddress := slotAddress(flushIndex)
            victimDirty := dirty(flushIndex)
            valid(flushIndex) := false.B
            dirty(flushIndex) := false.B
            state := evictCapture
        }.otherwise {
            when(flushIndex === (lines - 1).U) {
                flushFinished := true.B
                flushActive := false.B
                state := idle
            }.otherwise { flushIndex := flushIndex + 1.U }
        }
    }
    when(cpuFire) {
        when(state === idle) {
            pending := request
            pendingIndex := index
            pendingBypass := bypass
        }.otherwise {
            assert(hitUnderMiss, "only independent read hits may pass an outstanding cache miss")
        }
        when(needsEviction) {
            victimAddress := slotAddress(index)
            victimDirty := dirty(index)
            valid(index) := false.B
            dirty(index) := false.B
            state := evictCapture
        }.elsewhen(bypass) {
            state := bypassResponse
        }.elsewhen(writeHit) {
            touch(index)
            dirty(index) := true.B
            readPending := true.B
            storePending := true.B
        }.elsewhen(readHit) {
            touch(index)
            hitBank := request.address(5, 3)
            readPending := true.B
        }.otherwise { state := acquire }
    }
    when(state === evictCapture) {
        for (i <- 0 until 8) { victimWords(i) := readWords(i) }
        releaseBeat := 0.U
        state := evictSend
    }
    io.tl.c.valid := state === evictSend || state === probeSend
    io.tl.c.bits := 0.U.asTypeOf(io.tl.c.bits)
    io.tl.c.bits.opcode := Mux(state === evictSend,
        Mux(victimDirty, TLOpcode.ReleaseData, TLOpcode.Release),
        Mux(probeDirty, TLOpcode.ProbeAckData, TLOpcode.ProbeAck))
    io.tl.c.bits.param := Mux(state === evictSend, TLPermissions.tToN,
        Mux(probeHit, TLPermissions.tToN, 5.U))
    io.tl.c.bits.size := 6.U
    io.tl.c.bits.source := Mux(state === evictSend, 0.U, probeSource)
    io.tl.c.bits.address := Mux(state === evictSend, victimAddress, probeAddress)
    io.tl.c.bits.data := Mux(state === evictSend, victimWords(releaseBeat), probeWords(probeBeat))
    when(io.tl.c.fire && state === evictSend) {
        when(!victimDirty || releaseBeat === 7.U) { state := evictAck }
            .otherwise { releaseBeat := releaseBeat + 1.U }
    }
    when(io.tl.d.fire && io.tl.d.bits.opcode === TLOpcode.ReleaseAck) {
        assert(state === evictAck && io.tl.d.bits.source === 0.U &&
            !io.tl.d.bits.denied && !io.tl.d.bits.corrupt, "cache ReleaseAck invalid")
        when(flushActive) {
            when(flushIndex === (lines - 1).U) {
                flushFinished := true.B
                flushActive := false.B
                state := idle
            }.otherwise {
                flushIndex := flushIndex + 1.U
                state := flushScan
            }
        }.otherwise { state := Mux(pendingBypass, bypassSend, acquire) }
    }
    when(state === bypassSend && io.downstream.request.fire) { state := bypassResponse }
    when(state === bypassResponse && io.upstream.response.fire) { state := idle }

    private val engine = Module(new TileLinkLineAcquireEngine(params, entries = 4))
    refillResultPending := engine.io.response.valid
    engine.io.request.valid := state === acquire && !io.tl.b.valid
    engine.io.request.bits.address := Cat(pending.address(63, 6), 0.U(6.W))
    engine.io.request.bits.tag := 0.U
    engine.io.request.bits.grow := TLPermissions.nToT
    engine.io.request.bits.permissionOnly := false.B
    when(engine.io.request.fire) { state := fill }
    engine.io.response.ready := state === fill
    val fillIndex = pendingIndex
    val selected = pending.address(5, 3)
    val writeHitFire = cpuFire && state === idle && !needsEviction && !bypass && writeHit
    for (i <- 0 until 8) {
        val original = engine.io.response.bits.data(64 * i + 63, 64 * i)
        val filled = Mux(pending.write && selected === i.U && !engine.io.response.bits.error,
            merge(original, pending), original)
        val hitBankWrite = writeHitFire && request.address(5, 3) === i.U
        when(engine.io.response.fire || hitBankWrite) {
            data(i).write(Mux(engine.io.response.fire, fillIndex, index),
                Mux(engine.io.response.fire, filled, request.data).asTypeOf(Vec(8, UInt(8.W))),
                Mux(engine.io.response.fire, 255.U(8.W), request.mask).asBools)
        }
    }
    when(engine.io.response.fire) {
        assert(engine.io.response.bits.cap === TLPermissions.toT || engine.io.response.bits.error,
            "write-back L1 requires T permission")
        val word = (engine.io.response.bits.data >> (selected << 6))(63, 0)
        when(!engine.io.response.bits.error) {
            if (tagConfig.compact) assert(tagGeometry.contains(pending.address), "tag install outside aperture")
            tags(fillIndex) := lineTag(pending.address)
            valid(fillIndex) := true.B
            dirty(fillIndex) := pending.write
            touch(fillIndex)
        }
        missResult.data := Mux(pending.write, 0.U, word)
        missResult.error := engine.io.response.bits.error
        missResult.pageFault := false.B
        state := missResponse
    }
    when(state === missResponse && io.upstream.response.fire) { state := idle }
    io.tl.a <> engine.io.a
    engine.io.d.valid := io.tl.d.valid && io.tl.d.bits.opcode =/= TLOpcode.ReleaseAck
    engine.io.d.bits := io.tl.d.bits
    io.tl.d.ready := Mux(io.tl.d.bits.opcode === TLOpcode.ReleaseAck, state === evictAck, engine.io.d.ready)
    io.tl.e <> engine.io.e

    when(io.tl.b.fire) {
        assert(io.tl.b.bits.opcode === TLOpcode.ProbeBlock && io.tl.b.bits.size === 6.U &&
            io.tl.b.bits.param === TLPermissions.toN, "private cache expects an invalidation probe")
        val probeIndex = residentSlot(io.tl.b.bits.address)
        probeAddress := io.tl.b.bits.address
        probeSource := io.tl.b.bits.source
        // B and the pending CPU reply may both handshake in this cycle. Resume
        // idle in that case, not a response state whose credit was consumed.
        probeResume := Mux((state === bypassResponse || state === missResponse) &&
            io.upstream.response.fire, idle, state)
        probeHit := tagGeometry.qualifies(io.tl.b.bits.address) && valid(probeIndex) && tags(probeIndex) === lineTag(io.tl.b.bits.address)
        probeDirty := tagGeometry.qualifies(io.tl.b.bits.address) && valid(probeIndex) && tags(probeIndex) === lineTag(io.tl.b.bits.address) &&
            dirty(probeIndex)
        when(tagGeometry.qualifies(io.tl.b.bits.address) && valid(probeIndex) && tags(probeIndex) === lineTag(io.tl.b.bits.address)) {
            valid(probeIndex) := false.B
            dirty(probeIndex) := false.B
        }
        state := probeCapture
    }
    when(state === probeCapture) {
        for (i <- 0 until 8) { probeWords(i) := readWords(i) }
        probeBeat := 0.U
        state := probeSend
    }
    private val probeReplyConsumed = probing && (bypassReply || missReply) && io.upstream.response.fire
    when(probeReplyConsumed) { probeResume := idle }
    when(io.tl.c.fire && state === probeSend) {
        when(!probeDirty || probeBeat === 7.U) {
            state := Mux(probeReplyConsumed, idle, probeResume)
        }
            .otherwise { probeBeat := probeBeat + 1.U }
    }
}
