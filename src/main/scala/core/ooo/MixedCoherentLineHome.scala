package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLParams, TLOpcode, TLPermissions}
import soc.ip.tilelink.{TileLinkLineProbeEngine, TileLinkLineTransfer}

/** Single-client bounded read/refill and writeback ownership tables.
  * Complete C transfers a dirty victim into the pending-writeback table before
  * its directory slot may be reused. Write completion never clears a reused slot.
  * One A acceptance/cycle, one D beat/cycle, M refill and W release line buffers.
  * DMA/atomic maintenance remains a drain barrier; Grant bursts retain their lock.
  * With mixedReadWrite, disjoint new refills may overlap queued dirty writebacks.
  */
class MixedCoherentLineHome(
    params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 2),
    base: BigInt = BigInt("80010000", 16),
    bytes: BigInt = 8192,
    trackedLines: Int = 128,
    trackedWays: Int = 2,
    acquireEntries: Int = 2,
    rawResponseMetadata: Boolean = false,
    tagConfig: CacheTagConfig = CacheTagConfig.FullWidth,
    writebackEntries: Int = 1,
    mixedReadWrite: Boolean = false,
    dmaLineTransfers: Boolean = false
) extends CoherentLineHomeModule(params, 1, dmaLineTransfers) {
    require(params.addrWidth == 64 && params.dataWidth == 64 && params.sourceBits >= 3)
    require(Set(2, 4).contains(acquireEntries) && params.sinkBits >= log2Ceil(acquireEntries))
    require(bytes >= 64 && isPow2(bytes) && base % 64 == 0 && base + bytes <= (BigInt(1) << 64))
    require(trackedLines >= 4 && isPow2(trackedLines) && trackedLines <= bytes / 64)
    require(Set(1, 2).contains(trackedWays) && trackedLines / trackedWays >= acquireEntries,
        "each Acquire entry needs an independently reservable directory set")
    require(Set(1, 2, 4).contains(writebackEntries))
    require(params.sourceBits >= log2Ceil(acquireEntries + writebackEntries))
    private val writeTagBits = math.max(log2Ceil(acquireEntries + (if (dmaLineTransfers) 1 else 0)),
        log2Ceil(writebackEntries + (if (dmaLineTransfers) 2 else 1)))
    private val releaseBits = math.max(1, log2Ceil(writebackEntries))
    private val port = io.clients(0)
    private val entryBits = log2Ceil(acquireEntries)
    private val directoryBits = log2Ceil(trackedLines)
    private val setBits = log2Ceil(trackedLines / trackedWays)
    private def setOf(address: UInt): UInt = address(5 + setBits, 6)
    private def inRam(address: UInt): Bool = address >= base.U(65.W) && address < (base + bytes).U(65.W)
    private val owned = RegInit(VecInit(Seq.fill(trackedLines)(false.B)))
    // The directory index already identifies the set; tags need not store
    // those bits again. Keep ownership metadata separately resettable.
    private val tagGeometry = tagConfig.geometry(base, bytes, 6 + setBits)
    private val tagBanks = Seq.fill(trackedWays)(Mem(trackedLines / trackedWays, UInt(tagGeometry.tagBits.W)))
    private val tagLookupAddress = WireDefault(io.upstream.request.bits.address)
    // Two functional read clients remain independent: a first Release C beat
    // and the live upstream / saved maintenance lookup. A third read serves
    // only the independent Acquire admission assertion; synthesis must prove
    // that verification-only cone is pruned before claiming two RAM copies.
    private val lookupTags = tagBanks.map(_.read(setOf(tagLookupAddress)))
    private val releaseTags = tagBanks.map(_.read(setOf(port.c.bits.address)))
    private val acquireTags = tagBanks.map(_.read(setOf(port.a.bits.address)))
    private def waySlot(address: UInt, way: Int): UInt =
        if (trackedWays == 1) setOf(address) else Cat(way.U(1.W), setOf(address))
    private def wayHit(address: UInt, way: Int, readTags: Seq[UInt]): Bool = {
        val slot = waySlot(address, way)
        tagGeometry.qualifies(address) && owned(slot) && readTags(way) === tagGeometry.tag(address)
    }
    private def lineOwned(address: UInt, readTags: Seq[UInt]): Bool =
        (0 until trackedWays).map(wayHit(address, _, readTags)).reduce(_ || _)
    private def ownedSlot(address: UInt, readTags: Seq[UInt]): UInt =
        if (trackedWays == 1) waySlot(address, 0)
        else Mux(wayHit(address, 0, readTags), waySlot(address, 0), waySlot(address, 1))
    private def freeDirectory(address: UInt): Bool =
        (0 until trackedWays).map(i => !owned(waySlot(address, i))).reduce(_ || _)
    private def freeDirectorySlot(address: UInt): UInt =
        if (trackedWays == 1) waySlot(address, 0)
        else Mux(!owned(waySlot(address, 0)), waySlot(address, 0), waySlot(address, 1))

    private val free :: queued :: filling :: grantReady :: waitE :: Nil = Enum(5)
    private val phase = RegInit(VecInit(Seq.fill(acquireEntries)(free)))
    private val addresses = Reg(Vec(acquireEntries, UInt(64.W)))
    private val sources = Reg(Vec(acquireEntries, UInt(params.sourceBits.W)))
    private val directory = Reg(Vec(acquireEntries, UInt(directoryBits.W)))
    private val data = Reg(Vec(acquireEntries, Vec(8, UInt(64.W))))
    private val errors = Reg(Vec(acquireEntries, Bool()))
    private val active = VecInit(phase.map(_ =/= free))
    private val anyAcquire = active.asUInt.orR
    private def transientSet(address: UInt): Bool =
        (0 until acquireEntries).map(i => active(i) && setOf(addresses(i)) === setOf(address)).reduce(_ || _)
    private val freeMask = VecInit(phase.map(_ === free))
    private val allocate = PriorityEncoder(freeMask)
    private val fillQueue = Module(new Queue(UInt(entryBits.W), acquireEntries, pipe = false, flow = false))
    private val transfer = Module(new TileLinkLineTransfer(params.copy(sourceBits = params.sourceBits - 1),
        entries = 4, tagBits = writeTagBits, rawResponseMetadata = rawResponseMetadata))
    io.line <> transfer.io.tl
    private val sendEntry = Mux(fillQueue.io.deq.valid, fillQueue.io.deq.bits, 0.U)
    private val readDispatchAllowed = WireDefault(true.B)
    private val releaseRetired = WireDefault(false.B)
    private val yieldedToRelease = RegInit(false.B)
    // At most one completed release may delay a queued fill head. Once that
    // debt is paid, dispatch has priority until the engine accepts the request.
    when(releaseRetired && fillQueue.io.deq.valid) { yieldedToRelease := true.B }
    when(!fillQueue.io.deq.valid || transfer.io.readRequest.fire) { yieldedToRelease := false.B }
    private val directFillOffer = WireDefault(false.B)
    private val directFillFire = directFillOffer && transfer.io.readRequest.fire
    transfer.io.readRequest.valid := (fillQueue.io.deq.valid || directFillOffer) && readDispatchAllowed
    transfer.io.readRequest.bits.address := Mux(directFillOffer, port.a.bits.address, addresses(sendEntry))
    transfer.io.readRequest.bits.tag := Mux(directFillOffer, allocate, sendEntry)
    fillQueue.io.deq.ready := transfer.io.readRequest.ready && readDispatchAllowed
    when(transfer.io.readRequest.fire && transfer.io.readRequest.bits.tag < acquireEntries.U) {
        when(directFillOffer) {
            assert(port.a.fire && !fillQueue.io.deq.valid && phase(allocate) === free,
                "direct home fill requires the newly accepted free owner")
        }.otherwise {
            assert(phase(sendEntry) === queued, "home fill dispatch lost acquire owner")
            phase(sendEntry) := filling
        }
    }
    private val fillEntry = transfer.io.readResponse.bits.tag(entryBits - 1, 0)
    transfer.io.readResponse.ready := true.B
    when(transfer.io.readResponse.fire && transfer.io.readResponse.bits.tag < acquireEntries.U) {
        assert(transfer.io.readResponse.bits.tag < acquireEntries.U && phase(fillEntry) === filling, "home refill result has no acquire owner")
        data(fillEntry) := transfer.io.readResponse.bits.data.asTypeOf(data(fillEntry))
        errors(fillEntry) := transfer.io.readResponse.bits.error
        phase(fillEntry) := grantReady
    }

    // Voluntary releases are accepted independently of live fills and GrantAck.
    private val rIdle :: rCapture :: rSend :: rWait :: rAck :: Nil = Enum(5)
    private val releasePhases = RegInit(VecInit(Seq.fill(writebackEntries)(rIdle)))
    private val releaseAddresses = Reg(Vec(writebackEntries, UInt(64.W)))
    private val releaseSources = Reg(Vec(writebackEntries, UInt(params.sourceBits.W)))
    private val releaseDirectories = Reg(Vec(writebackEntries, UInt(directoryBits.W)))
    private val releaseData = Reg(Vec(writebackEntries, Vec(8, UInt(64.W))))
    private val releaseBeat = Reg(UInt(3.W))
    private val captureEntry = Reg(UInt(releaseBits.W))
    private val capturing = RegInit(false.B)
    private val releaseFree = VecInit(releasePhases.map(_ === rIdle))
    private val newRelease = PriorityEncoder(releaseFree)
    private val captureSlot = Mux(capturing, captureEntry, newRelease)
    private val releasePhase = releasePhases(captureSlot)
    private val releaseBusy = releasePhases.map(_ =/= rIdle).reduce(_ || _)
    private def releaseSet(address: UInt): Bool = (0 until writebackEntries).map(i =>
        releasePhases(i) =/= rIdle && (if (mixedReadWrite) address(63, 6) === releaseAddresses(i)(63, 6)
            else setOf(address) === setOf(releaseAddresses(i)))).reduce(_ || _)
    private val isRelease = TLOpcode.isRelease(port.c.bits.opcode)
    private val releaseOffer = port.c.valid && isRelease
    private val probeCActive = RegInit(false.B)
    private val probeCBeat = RegInit(0.U(3.W))
    private val probeCSource = Reg(UInt(params.sourceBits.W))
    private val releaseSourceBusy = (0 until writebackEntries).map(i =>
        releasePhases(i) =/= rIdle && releaseSources(i) === port.c.bits.source).reduce(_ || _)
    private val releaseReady = !probeCActive && (capturing ||
        (releaseFree.asUInt.orR && !transientSet(port.c.bits.address) &&
            !releaseSet(port.c.bits.address) && !releaseSourceBusy))
    private val releaseQueue = Module(new Queue(UInt(releaseBits.W), writebackEntries))
    releaseQueue.io.enq.valid := port.c.fire && isRelease &&
        port.c.bits.opcode === TLOpcode.ReleaseData && capturing && releaseBeat === 7.U
    releaseQueue.io.enq.bits := captureSlot
    when(releaseQueue.io.enq.valid) { assert(releaseQueue.io.enq.ready, "reserved release FIFO overflow") }
    readDispatchAllowed := (if (mixedReadWrite) true.B else
        yieldedToRelease || !(releaseBusy || (releaseOffer && releaseReady)))
    when(port.c.fire && isRelease) {
        assert(!port.c.bits.corrupt && port.c.bits.size === 6.U && port.c.bits.param === TLPermissions.tToN,
            "invalid release size/permission/corruption")
        when(!capturing) {
            assert(inRam(port.c.bits.address) && port.c.bits.address(5, 0) === 0.U &&
                lineOwned(port.c.bits.address, releaseTags), "release has no committed directory owner")
            captureEntry := newRelease
            releaseAddresses(newRelease) := port.c.bits.address
            releaseSources(newRelease) := port.c.bits.source
            releaseDirectories(newRelease) := ownedSlot(port.c.bits.address, releaseTags)
            releaseData(newRelease)(0) := port.c.bits.data
            releaseBeat := 1.U
            when(port.c.bits.opcode === TLOpcode.ReleaseData) {
                releasePhases(newRelease) := rCapture; capturing := true.B
            }.otherwise { owned(ownedSlot(port.c.bits.address, releaseTags)) := false.B; releasePhases(newRelease) := rAck }
        }.otherwise {
            assert(releasePhase === rCapture && port.c.bits.opcode === TLOpcode.ReleaseData &&
                port.c.bits.address === releaseAddresses(captureSlot) && port.c.bits.source === releaseSources(captureSlot),
                "release burst changed address/source/opcode")
            releaseData(captureSlot)(releaseBeat) := port.c.bits.data
            when(releaseBeat === 7.U) {
                releasePhases(captureSlot) := rSend; capturing := false.B
                if (mixedReadWrite) owned(releaseDirectories(captureSlot)) := false.B
            }
                .otherwise { releaseBeat := releaseBeat + 1.U }
        }
    }
    when(port.c.valid && capturing) {
        assert(isRelease, "probe C interleaved a release burst")
    }

    // Ordinary direct reads retain the old ordered downstream protocol. A pending
    // upstream request prevents an endless Acquire stream from starving DMA.
    private val Seq(mIdle, mProbeSend, mProbeWait, mWriteSend, mWriteWait, mAccessSend, mAccessWait,
        mLineReadSend, mLineReadWait, mLineWriteSend, mLineWriteWait, mLineResponse) = Enum(12)
    private val maintenance = RegInit(mIdle)
    private val access = Reg(new DataRequest)
    private val lineAccess = if (dmaLineTransfers) RegInit(false.B) else WireDefault(false.B)
    private val lineWriteData = if (dmaLineTransfers) Some(Reg(UInt(512.W))) else None
    private val lineError = if (dmaLineTransfers) Some(RegInit(false.B)) else None
    private val linePending = io.dmaLine.map(_.request.valid).getOrElse(false.B)
    private val selectLine = WireDefault(false.B)
    private val accessSend = Mux(lineAccess, Mux(access.write, mLineWriteSend, mLineReadSend), mAccessSend)
    // Both selection and ownership come from registered state. Never insert
    // A.ready/fire or Release priority in this functional tag-address path.
    tagLookupAddress := Mux(maintenance === mProbeSend, access.address,
        Mux(selectLine, io.dmaLine.map(_.request.bits.address).getOrElse(0.U), io.upstream.request.bits.address))
    private val maintenanceDirectory = Reg(UInt(directoryBits.W))
    private val maintenanceData = Reg(UInt(512.W))
    private val reads = RegInit(0.U(4.W))
    private val directHeld = RegInit(false.B)
    io.drainDone := maintenance === mIdle && !anyAcquire && reads === 0.U &&
        !directHeld && !releaseBusy && !releaseOffer && !probeCActive
    private val upperWaiting = RegInit(false.B)
    private val preferAcquire = RegInit(false.B)
    when(port.a.fire) { preferAcquire := false.B }
    when(io.upstream.request.fire) { preferAcquire := true.B }
    when(io.upstream.request.valid || linePending) { upperWaiting := true.B }
    when(io.upstream.request.fire || (!io.upstream.request.valid && !linePending)) { upperWaiting := false.B }
    private val request = io.upstream.request.bits
    private val needsProbe = !io.upstreamRequestCpu && inRam(request.address) && lineOwned(request.address, lookupTags)
    private val needsMaintenance = request.write || needsProbe
    private val sourceBusy = (0 until acquireEntries).map(i =>
        active(i) && sources(i) === port.a.bits.source).reduce(_ || _)
    private val canAcquire = !io.drainRequest && maintenance === mIdle && reads === 0.U && !directHeld &&
        ((!upperWaiting && !io.upstream.request.valid && !linePending) || preferAcquire) &&
        freeMask.asUInt.orR && fillQueue.io.enq.ready && !sourceBusy &&
        !transientSet(port.a.bits.address) && !releaseSet(port.a.bits.address) &&
        !(releaseOffer && setOf(port.c.bits.address) === setOf(port.a.bits.address)) &&
        freeDirectory(port.a.bits.address)
    port.a.ready := canAcquire
    // Reader readiness does not affect A admission. A failed direct dispatch
    // falls back to the existing FIFO with the same reserved metadata/tag.
    directFillOffer := port.a.fire && !fillQueue.io.deq.valid && readDispatchAllowed
    fillQueue.io.enq.valid := port.a.fire && !directFillFire
    fillQueue.io.enq.bits := allocate
    when(port.a.fire) {
        assert(port.a.bits.opcode === TLOpcode.AcquireBlock && port.a.bits.param === TLPermissions.nToT &&
            port.a.bits.size === 6.U && port.a.bits.address(5, 0) === 0.U &&
            inRam(port.a.bits.address) && !lineOwned(port.a.bits.address, acquireTags) && !port.a.bits.corrupt,
            "home accepts only an aligned unowned nToT AcquireBlock")
        addresses(allocate) := port.a.bits.address
        sources(allocate) := port.a.bits.source
        directory(allocate) := freeDirectorySlot(port.a.bits.address)
        errors(allocate) := false.B
        phase(allocate) := Mux(directFillFire, filling, queued)
    }
    private val upperOpen = !io.drainRequest && maintenance === mIdle && !anyAcquire &&
        (!releaseBusy || directHeld) && (!port.a.valid || !preferAcquire) && !releaseOffer
    private val directRead = io.upstream.request.valid && !selectLine && !needsMaintenance &&
        (directHeld || (upperOpen && reads < 8.U))
    io.downstream.request.valid := directRead || maintenance === mAccessSend
    io.downstream.request.bits := Mux(maintenance === mAccessSend, access, request)
    io.upstream.request.ready := !selectLine && (directHeld || upperOpen) &&
        Mux(needsMaintenance, reads === 0.U, reads < 8.U && io.downstream.request.ready)
    io.upstream.response.valid := io.downstream.response.valid &&
        (maintenance === mAccessWait || (maintenance === mIdle && reads =/= 0.U))
    io.upstream.response.bits := io.downstream.response.bits
    io.downstream.response.ready := io.upstream.response.ready &&
        (maintenance === mAccessWait || (maintenance === mIdle && reads =/= 0.U))
    when(directRead && !io.downstream.request.ready) { directHeld := true.B }
    when(directRead && io.downstream.request.fire) { directHeld := false.B }
    when(directHeld) {
        assert(maintenance === mIdle && !anyAcquire && io.upstream.request.valid && !needsMaintenance,
            "stalled direct read must remain irrevocable")
    }
    private val startRead = io.upstream.request.fire && !needsMaintenance
    private val finishRead = io.upstream.response.fire && maintenance === mIdle
    when(startRead =/= finishRead) { reads := Mux(startRead, reads + 1.U, reads - 1.U) }
    assert(reads <= 8.U, "home direct read credit overflow")
    when(io.upstream.request.fire && needsMaintenance) {
        assert(!anyAcquire && reads === 0.U && !releaseBusy, "maintenance crossed active acquire/release")
        access := request
        if (dmaLineTransfers) lineAccess := false.B
        maintenanceDirectory := ownedSlot(request.address, lookupTags)
        maintenance := Mux(needsProbe, mProbeSend, mAccessSend)
    }
    when(maintenance === mAccessSend && io.downstream.request.fire) { maintenance := mAccessWait }
    when(maintenance === mAccessWait && io.upstream.response.fire) { maintenance := mIdle }

    private val probe = Module(new TileLinkLineProbeEngine(params, entries = 2, tagBits = 1))
    port.b <> probe.io.probe
    // A not-yet-issued probe can disappear only before entering the engine.
    // An issued probe completes after any racing voluntary ReleaseAck.
    private val probeStillOwned = lineOwned(access.address, lookupTags)
    probe.io.request.valid := maintenance === mProbeSend && probeStillOwned && !releaseOffer && !releaseBusy
    probe.io.request.bits.address := Cat(access.address(63, 6), 0.U(6.W))
    probe.io.request.bits.tag := 0.U
    when(maintenance === mProbeSend && !probeStillOwned && !releaseBusy) { maintenance := accessSend }
    when(probe.io.request.fire) { maintenance := mProbeWait }
    probe.io.ack.valid := port.c.valid && !isRelease && !capturing
    probe.io.ack.bits := port.c.bits
    port.c.ready := Mux(isRelease, releaseReady, !capturing && probe.io.ack.ready)
    when(port.c.valid && probeCActive) {
        assert(port.c.bits.opcode === TLOpcode.ProbeAckData && port.c.bits.source === probeCSource,
            "C message interleaved a probe-data burst")
    }
    when(port.c.fire && !isRelease && port.c.bits.opcode === TLOpcode.ProbeAckData) {
        probeCSource := port.c.bits.source
        probeCBeat := probeCBeat + 1.U
        probeCActive := probeCBeat =/= 7.U
    }
    probe.io.response.ready := maintenance === mProbeWait && !releaseBusy && !releaseOffer
    when(probe.io.response.fire) {
        assert(!probe.io.response.bits.corrupt, "dirty probe data must not be corrupt")
        owned(maintenanceDirectory) := false.B
        maintenanceData := probe.io.response.bits.data
        maintenance := Mux(probe.io.response.bits.hasData, mWriteSend, accessSend)
    }

    // The shared dispatch retains queued origins and explicitly bypasses only
    // an empty queue with one offered origin; stalled offers spill unchanged.
    private val writes = Module(new CoherentWriteDispatch(params.addrWidth, writeTagBits))
    private val sendReleaseSlot = Mux(releaseQueue.io.deq.valid, releaseQueue.io.deq.bits, 0.U)
    writes.io.in(0).valid := releaseQueue.io.deq.valid
    writes.io.in(0).bits.address := releaseAddresses(sendReleaseSlot)
    writes.io.in(0).bits.data := releaseData(sendReleaseSlot).asUInt
    writes.io.in(0).bits.tag := sendReleaseSlot
    releaseQueue.io.deq.ready := writes.io.in(0).ready
    writes.io.in(1).valid := maintenance === mWriteSend || maintenance === mLineWriteSend
    writes.io.in(1).bits.address := Cat(access.address(63, 6), 0.U(6.W))
    writes.io.in(1).bits.data := Mux(maintenance === mLineWriteSend, lineWriteData.getOrElse(0.U), maintenanceData)
    writes.io.in(1).bits.tag := Mux(maintenance === mLineWriteSend, (writebackEntries + 1).U, writebackEntries.U)
    transfer.io.writeRequest <> writes.io.out
    when(writes.io.in(0).fire) { releasePhases(sendReleaseSlot) := rWait }
    when(writes.io.in(1).fire) { maintenance := Mux(maintenance === mLineWriteSend, mLineWriteWait, mWriteWait) }
    transfer.io.writeResponse.ready := true.B
    when(transfer.io.writeResponse.fire) {
        when(transfer.io.writeResponse.bits.tag <= writebackEntries.U) {
            assert(!transfer.io.writeResponse.bits.error, "coherent home backing rejected dirty writeback")
        }
        when(transfer.io.writeResponse.bits.tag < writebackEntries.U) {
            val slot = if (writebackEntries == 1) 0.U else transfer.io.writeResponse.bits.tag(releaseBits - 1, 0)
            assert(releasePhases(slot) === rWait, "writeback result has no release owner")
            if (!mixedReadWrite) owned(releaseDirectories(slot)) := false.B
            releasePhases(slot) := rAck
        }.elsewhen(transfer.io.writeResponse.bits.tag === writebackEntries.U) {
            assert(transfer.io.writeResponse.bits.tag === writebackEntries.U && maintenance === mWriteWait,
                "writeback result has no maintenance owner")
            maintenance := accessSend
        }
    }

    if (dmaLineTransfers) {
        val line = io.dmaLine.get
        val preferLine = RegInit(true.B)
        selectLine := line.request.valid && !directHeld &&
            (preferLine || !io.upstream.request.valid)
        when(io.upstream.request.fire) { preferLine := true.B }
        line.request.ready := selectLine && upperOpen && reads === 0.U
        line.response.valid := maintenance === mLineResponse
        line.response.bits.data := Mux(lineError.get, 0.U, maintenanceData)
        line.response.bits.error := lineError.get
        when(line.request.fire) {
            assert(!anyAcquire && reads === 0.U && !releaseBusy && !directHeld,
                "line DMA crossed a coherence owner")
            assert(line.request.bits.address(5, 0) === 0.U && inRam(line.request.bits.address) &&
                (line.request.bits.address +& 64.U) <= (base + bytes).U(65.W),
                "line DMA only accepts a complete naturally aligned RAM line")
            access := 0.U.asTypeOf(new DataRequest)
            access.address := line.request.bits.address
            access.write := line.request.bits.write
            lineWriteData.get := line.request.bits.data
            lineError.get := false.B
            lineAccess := true.B
            maintenanceDirectory := ownedSlot(line.request.bits.address, lookupTags)
            maintenance := Mux(lineOwned(line.request.bits.address, lookupTags), mProbeSend,
                Mux(line.request.bits.write, mLineWriteSend, mLineReadSend))
            preferLine := false.B
            preferAcquire := true.B
            upperWaiting := false.B
        }
        when(maintenance === mLineReadSend) {
            assert(!fillQueue.io.deq.valid && !anyAcquire, "line DMA overlaps refill dispatch")
            transfer.io.readRequest.valid := true.B
            transfer.io.readRequest.bits.address := access.address
            transfer.io.readRequest.bits.tag := acquireEntries.U
            when(transfer.io.readRequest.fire) { maintenance := mLineReadWait }
        }
        when(transfer.io.readResponse.fire && transfer.io.readResponse.bits.tag === acquireEntries.U) {
            assert(maintenance === mLineReadWait && lineAccess, "DMA read result lost its line owner")
            maintenanceData := transfer.io.readResponse.bits.data
            lineError.get := transfer.io.readResponse.bits.error
            maintenance := mLineResponse
        }
        when(transfer.io.writeResponse.fire && transfer.io.writeResponse.bits.tag === (writebackEntries + 1).U) {
            assert(maintenance === mLineWriteWait && lineAccess, "DMA write result lost its line owner")
            maintenanceData := 0.U
            lineError.get := transfer.io.writeResponse.bits.error
            maintenance := mLineResponse
        }
        when(line.response.fire) { maintenance := mIdle; lineAccess := false.B }
    }
    when(transfer.io.readResponse.fire) {
        assert(transfer.io.readResponse.bits.tag < (acquireEntries + (if (dmaLineTransfers) 1 else 0)).U,
            "home read result has an unknown full tag")
    }
    when(transfer.io.writeResponse.fire) {
        assert(transfer.io.writeResponse.bits.tag < (writebackEntries + (if (dmaLineTransfers) 2 else 1)).U,
            "home write result has an unknown full tag")
    }

    private val dLocked = RegInit(false.B)
    private val dRelease = Reg(Bool())
    private val dEntry = Reg(UInt(entryBits.W))
    private val dBeat = RegInit(0.U(3.W))
    private val dTurn = RegInit(0.U(entryBits.W))
    private val grantMask = VecInit(phase.map(_ === grantReady))
    private val afterTurn = VecInit((0 until acquireEntries).map(i => grantMask(i) && i.U >= dTurn))
    private val selectedGrant = Mux(afterTurn.asUInt.orR, PriorityEncoder(afterTurn), PriorityEncoder(grantMask))
    private val releaseAckMask = VecInit(releasePhases.map(_ === rAck))
    private val heldRelease = Reg(UInt(releaseBits.W))
    private val ackRelease = Mux(dLocked, heldRelease, PriorityEncoder(releaseAckMask))
    private val sendRelease = Mux(dLocked, dRelease, releaseAckMask.asUInt.orR)
    private val grantEntry = Mux(dLocked, dEntry, selectedGrant)
    port.d.valid := Mux(sendRelease, releaseAckMask(ackRelease), grantMask(grantEntry))
    port.d.bits := 0.U.asTypeOf(port.d.bits)
    port.d.bits.opcode := Mux(sendRelease, TLOpcode.ReleaseAck, TLOpcode.GrantData)
    port.d.bits.param := Mux(sendRelease, 0.U, TLPermissions.toT)
    port.d.bits.size := 6.U
    port.d.bits.source := Mux(sendRelease, releaseSources(ackRelease), sources(grantEntry))
    port.d.bits.sink := Mux(sendRelease, 0.U, grantEntry)
    port.d.bits.denied := !sendRelease && errors(grantEntry)
    port.d.bits.corrupt := !sendRelease && errors(grantEntry)
    port.d.bits.data := Mux(sendRelease || errors(grantEntry), 0.U, data(grantEntry)(dBeat))
    when(port.d.valid && !dLocked) { dLocked := true.B; dRelease := sendRelease; dEntry := grantEntry; heldRelease := ackRelease }
    when(port.d.fire) {
        when(sendRelease) {
            releaseRetired := true.B
            releasePhases(ackRelease) := rIdle
            dLocked := false.B
        }.elsewhen(dBeat === 7.U) {
            phase(grantEntry) := waitE
            dBeat := 0.U
            dTurn := grantEntry + 1.U
            dLocked := false.B
        }.otherwise { dBeat := dBeat + 1.U }
    }
    private val eInRange = port.e.bits.sink < acquireEntries.U
    private val eEntry = port.e.bits.sink(entryBits - 1, 0)
    port.e.ready := eInRange && phase(eEntry) === waitE
    when(port.e.valid) {
        assert(eInRange && active(eEntry), "GrantAck has no live sink")
    }
    when(port.e.fire) {
        when(!errors(eEntry)) {
            assert(!owned(directory(eEntry)), "reserved directory slot changed before GrantAck")
            if (tagConfig.compact) assert(tagGeometry.contains(addresses(eEntry)), "home tag outside aperture")
            assert(directory(eEntry)(setBits - 1, 0) === setOf(addresses(eEntry)),
                "GrantAck directory index lost its reserved set")
            for (way <- 0 until trackedWays) {
                val selectedWay = if (trackedWays == 1) true.B else directory(eEntry)(directoryBits - 1) === way.U
                when(selectedWay) {
                    tagBanks(way).write(directory(eEntry)(setBits - 1, 0), tagGeometry.tag(addresses(eEntry)))
                }
            }
            owned(directory(eEntry)) := true.B
        }
        phase(eEntry) := free
    }
    for (i <- 0 until acquireEntries; j <- i + 1 until acquireEntries) {
        when(active(i) && active(j)) {
            assert(sources(i) =/= sources(j), "duplicate live Acquire source")
            assert(setOf(addresses(i)) =/= setOf(addresses(j)), "overlapping transient cache sets")
            assert(directory(i) =/= directory(j), "duplicate reserved directory slot")
        }
    }
}
