package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLBundle, TLParams, TLOpcode, TLPermissions}
import soc.ip.tilelink.{TileLinkLineProbeEngine, TileLinkLineTransfer}

/** Reset-defined two-client arbitration for Home A and E. The same selected
  * client controls payload, valid, and ready, including the first post-reset
  * client-1-only transfer. A stalled offer retains its source until acceptance.
  * No registered data stage or transaction-credit restriction is introduced.
  */
class ResettableHomeClientArbiter[T <: Data](gen: T, nClients: Int = 2) extends Module {
    require(nClients == 2)
    val io = IO(new ArbiterIO(gen, nClients))
    private val turn = RegInit(0.U(1.W))
    private val held = RegInit(false.B)
    private val heldClient = Reg(UInt(1.W))
    private val offered = Mux(io.in(0).valid && io.in(1).valid, turn, io.in(1).valid.asUInt)
    private val selected = Mux(held, heldClient, offered)
    io.chosen := selected
    io.out.valid := io.in(selected).valid
    io.out.bits := io.in(selected).bits
    for (i <- 0 until nClients) io.in(i).ready := io.out.ready && selected === i.U
    when(io.out.valid && !io.out.ready && !held) {
        held := true.B
        heldClient := selected
    }
    when(io.out.fire) {
        turn := ~selected
        held := false.B
    }
    when(held) {
        assert(io.in(heldClient).valid, "Home arbitration source withdrew a held offer")
    }
    assert(PopCount(VecInit(io.in.map(_.fire))) === io.out.fire.asUInt,
        "Home arbitration input/output acceptance differs")
}

/** Bounded read/refill and writeback ownership tables with client-local sources.
  * Complete C transfers a dirty victim into the pending-writeback table before
  * its committed directory slot may be reused. An optional future reservation
  * starts after accepted first C, but cannot Grant before complete C.
  * Write completion never clears a reused slot.
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
    dmaLineTransfers: Boolean = false,
    dmaLineEntries: Int = 1,
    val distinctWayRelease: Boolean = false,
    val lineTransferDispatchFlow: Boolean = false,
    val lineReadChannel: Boolean = false,
    val internalLineGrant: Boolean = false,
    val memoryScheduleOverlap: Boolean = false,
    val futureWayReservation: Boolean = false,
    val sharedLookupMatch: Boolean = false,
    val nClients: Int = 1,
    val dmaMaintenanceCompletionFlow: Boolean = false,
    val dmaReadAcquireOverlap: Boolean = false,
    val dmaProbeAcquireOverlap: Boolean = false
) extends CoherentLineHomeModule(params, nClients, dmaLineTransfers, dmaLineEntries, lineReadChannel, internalLineGrant) {
    require(nClients >= 1 && nClients <= 2)
    require(!dmaProbeAcquireOverlap || dmaReadAcquireOverlap,
        "DMA Probe/Acquire overlap requires bounded DMA read/Acquire overlap")
    require(!dmaReadAcquireOverlap || (dmaLineTransfers && dmaLineEntries == 2 && nClients == 2 &&
        acquireEntries == 2 && writebackEntries == 2 && trackedLines == 1024 && trackedWays == 4 &&
        mixedReadWrite && lineReadChannel && internalLineGrant),
        "DMA read/Acquire overlap requires the bounded two-client, two-tag independent-line Home")
    require(!dmaMaintenanceCompletionFlow || (dmaLineTransfers && dmaLineEntries == 2),
        "maintenance completion flow requires the two-tag DMA line path")
    require(nClients == 1 || (!memoryScheduleOverlap && !futureWayReservation && !sharedLookupMatch &&
        !distinctWayRelease), "multi-client Home uses the generic ownership path")
    require(!sharedLookupMatch || (trackedLines == 512 && trackedWays == 2 && acquireEntries == 2 &&
        writebackEntries == 2 && mixedReadWrite && dmaLineTransfers && dmaLineEntries == 4 &&
        tagConfig.bankedStorage), "shared lookup requires qualified directory geometry")
    require(!(sharedLookupMatch && futureWayReservation) ||
        (memoryScheduleOverlap && lineTransferDispatchFlow && lineReadChannel && internalLineGrant),
        "combined shared/future lookup requires the isolated overlap/line-transport profile")
    require(Set(1, 2, 4, 8).contains(dmaLineEntries) && (dmaLineTransfers || dmaLineEntries == 1))
    require(params.addrWidth == 64 && params.dataWidth == 64 && params.sourceBits >= 3)
    require(Set(2, 4).contains(acquireEntries) && params.sinkBits >= log2Ceil(acquireEntries))
    require(bytes >= 64 && isPow2(bytes) && base % 64 == 0 && base + bytes <= (BigInt(1) << 64))
    require(trackedLines >= 4 && isPow2(trackedLines) && trackedLines <= bytes / 64)
    require(Set(1, 2, 4).contains(trackedWays) && trackedLines / trackedWays >= acquireEntries,
        "each Acquire entry needs an independently reservable directory set")
    require(Set(1, 2, 4).contains(writebackEntries))
    require(!memoryScheduleOverlap || (mixedReadWrite && acquireEntries == 2 &&
        writebackEntries == 2 && trackedWays == 2), "overlap requires exact two-way mixed ownership")
    require(!futureWayReservation || memoryScheduleOverlap,
        "future-way reservation requires the exact two-way overlap profile")
    require(!distinctWayRelease || (mixedReadWrite && acquireEntries == 2 &&
        writebackEntries == 2 && trackedWays == 2),
        "distinct-way release requires the original two-way mixed home profile")
    require(params.sourceBits >= log2Ceil(acquireEntries + writebackEntries))
    private val writeTagBits = math.max(log2Ceil(acquireEntries + (if (dmaLineTransfers) dmaLineEntries else 0)),
        log2Ceil(writebackEntries + (if (dmaLineTransfers) dmaLineEntries + 1 else 1)))
    private val releaseBits = math.max(1, log2Ceil(writebackEntries))
    private val clientBits = math.max(1, log2Ceil(nClients))
    private val aClient = WireDefault(0.U(clientBits.W))
    private val cClient = WireDefault(0.U(clientBits.W))
    private val eClient = WireDefault(0.U(clientBits.W))
    private val bClient = WireDefault(0.U(clientBits.W))
    private val dClient = WireDefault(0.U(clientBits.W))
    private val cLocked = WireDefault(false.B)
    private val cHeldClient = Reg(UInt(clientBits.W))
    private val port = if (nClients == 1) io.clients(0) else Wire(new TLBundle(params))
    if (nClients > 1) {
        val aArbiter = Module(new ResettableHomeClientArbiter(chiselTypeOf(port.a.bits), nClients))
        val eArbiter = Module(new ResettableHomeClientArbiter(chiselTypeOf(port.e.bits), nClients))
        for (i <- 0 until nClients) {
            aArbiter.io.in(i) <> io.clients(i).a
            eArbiter.io.in(i) <> io.clients(i).e
            io.clients(i).b.valid := port.b.valid && bClient === i.U
            io.clients(i).b.bits := port.b.bits
            io.clients(i).d.valid := port.d.valid && dClient === i.U
            io.clients(i).d.bits := port.d.bits
            io.clients(i).c.ready := port.c.ready && cClient === i.U
        }
        port.a.valid := aArbiter.io.out.valid
        port.a.bits := aArbiter.io.out.bits
        aArbiter.io.out.ready := port.a.ready
        aClient := aArbiter.io.chosen
        port.e.valid := eArbiter.io.out.valid
        port.e.bits := eArbiter.io.out.bits
        eArbiter.io.out.ready := port.e.ready
        eClient := eArbiter.io.chosen
        val releases = VecInit(io.clients.map(c => c.c.valid && TLOpcode.isRelease(c.c.bits.opcode)))
        val cValid = VecInit(io.clients.map(_.c.valid))
        cClient := Mux(cLocked, cHeldClient,
            Mux(releases.asUInt.orR, PriorityEncoder(releases), PriorityEncoder(cValid)))
        port.c.valid := io.clients(cClient).c.valid
        port.c.bits := io.clients(cClient).c.bits
        port.b.ready := io.clients(bClient).b.ready
        port.d.ready := io.clients(dClient).d.ready
    }
    when(port.c.fire) { cHeldClient := cClient }
    private val entryBits = log2Ceil(acquireEntries)
    private val directoryBits = log2Ceil(trackedLines)
    private val setBits = log2Ceil(trackedLines / trackedWays)
    private def setOf(address: UInt): UInt = address(5 + setBits, 6)
    private def inRam(address: UInt): Bool = address >= base.U(65.W) && address < (base + bytes).U(65.W)
    private val owned = RegInit(VecInit(Seq.fill(trackedLines)(false.B)))
    // Expose a single set/clear update for each directory bit in the bounded
    // overlap profile. GrantAck sets retain priority over every same-cycle
    // clear, including event combinations rejected by the protocol assertions.
    private val ownedClearValid = if (dmaReadAcquireOverlap) Seq.fill(3)(WireDefault(false.B)) else Seq.empty
    private val ownedClearSlot = if (dmaReadAcquireOverlap)
        Seq.fill(3)(WireDefault(0.U(directoryBits.W))) else Seq.empty
    private val ownedSetValid = if (dmaReadAcquireOverlap) WireDefault(false.B) else false.B
    private val ownedSetSlot = if (dmaReadAcquireOverlap) WireDefault(0.U(directoryBits.W)) else 0.U
    private def clearOwned(slot: UInt, event: Int): Unit = {
        if (dmaReadAcquireOverlap) {
            ownedClearValid(event) := true.B
            ownedClearSlot(event) := slot
        } else owned(slot) := false.B
    }
    if (dmaReadAcquireOverlap) {
        for (i <- 0 until trackedLines) {
            val set = ownedSetValid && ownedSetSlot === i.U
            val clear = (0 until 3).map(e => ownedClearValid(e) && ownedClearSlot(e) === i.U).reduce(_ || _)
            when(set || clear) { owned(i) := set }
        }
    }
    private val ownerClients = Reg(Vec(trackedLines, UInt(clientBits.W)))
    // The directory index already identifies the set; tags need not store
    // those bits again. Keep ownership metadata separately resettable.
    private val tagGeometry = tagConfig.geometry(base, bytes, 6 + setBits)
    private val tagBanks = Seq.fill(trackedWays)(Mem(trackedLines / trackedWays, UInt(tagGeometry.tagBits.W)))
    private val tagLookupAddress = WireDefault(UInt(64.W), io.upstream.request.bits.address)
    // Two functional read clients remain independent: a first Release C beat
    // and the live upstream / saved maintenance lookup. A third read serves
    // the independent Acquire admission assertion in the single-client profile.
    // Multi-client admission also uses it to find a competing committed owner;
    // that opt-in profile therefore makes no two-tag-read-port resource claim.
    private val lookupTags = tagBanks.map(_.read(setOf(tagLookupAddress)))
    private val releaseTags = tagBanks.map(_.read(setOf(port.c.bits.address)))
    private val acquireTags = tagBanks.map(_.read(setOf(port.a.bits.address)))
    private def waySlot(address: UInt, way: Int): UInt =
        if (trackedWays == 1) setOf(address) else Cat(way.U(log2Ceil(trackedWays).W), setOf(address))
    private def wayHit(address: UInt, way: Int, readTags: Seq[UInt]): Bool = {
        val slot = waySlot(address, way)
        tagGeometry.qualifies(address) && owned(slot) && readTags(way) === tagGeometry.tag(address)
    }
    private def lineOwned(address: UInt, readTags: Seq[UInt]): Bool =
        (0 until trackedWays).map(wayHit(address, _, readTags)).reduce(_ || _)
    private def ownedSlot(address: UInt, readTags: Seq[UInt]): UInt =
        if (trackedWays == 1) waySlot(address, 0)
        else if (trackedWays == 2) Mux(wayHit(address, 0, readTags), waySlot(address, 0), waySlot(address, 1))
        else Cat(PriorityEncoder(VecInit((0 until trackedWays).map(wayHit(address, _, readTags)))), setOf(address))
    private def directoryReserved(slot: UInt): Bool =
        (0 until acquireEntries).map(i => active(i) && directory(i) === slot).reduce(_ || _)
    private def directoryAvailable(address: UInt, way: Int): Bool = {
        val slot = waySlot(address, way)
        !owned(slot) && (if (memoryScheduleOverlap || nClients > 1)
            !(0 until acquireEntries).map(i => active(i) && directory(i) === slot).reduce(_ || _)
        else true.B)
    }
    private def freeDirectory(address: UInt): Bool =
        (0 until trackedWays).map(directoryAvailable(address, _)).reduce(_ || _)
    private def freeDirectorySlot(address: UInt): UInt =
        if (trackedWays == 1) waySlot(address, 0)
        else if (trackedWays == 2) Mux(directoryAvailable(address, 0), waySlot(address, 0), waySlot(address, 1))
        else Cat(PriorityEncoder(VecInit((0 until trackedWays).map(directoryAvailable(address, _)))), setOf(address))

    private val free :: queued :: filling :: grantReady :: waitE :: probing :: Nil = Enum(6)
    private val phase = RegInit(VecInit(Seq.fill(acquireEntries)(free)))
    private val addresses = Reg(Vec(acquireEntries, UInt(64.W)))
    private val sources = Reg(Vec(acquireEntries, UInt(params.sourceBits.W)))
    private val clients = Reg(Vec(acquireEntries, UInt(clientBits.W)))
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
        entries = 4, tagBits = writeTagBits, rawResponseMetadata = rawResponseMetadata,
        dispatchFlow = lineTransferDispatchFlow, lineReadChannel = lineReadChannel, isolatedWriteA = true))
    io.line <> transfer.io.tl
    io.lineRead.foreach(_ <> transfer.io.lineRead.get)
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
    private val releaseClients = Reg(Vec(writebackEntries, UInt(clientBits.W)))
    private val releaseDirectories = Reg(Vec(writebackEntries, UInt(directoryBits.W)))
    private val releaseData = Reg(Vec(writebackEntries, Vec(8, UInt(64.W))))
    private val releaseBeat = Reg(UInt(3.W))
    private val captureEntry = Reg(UInt(releaseBits.W))
    private val capturing = RegInit(false.B)
    // Only an accepted, registered dirty capture can lend its exact directory.
    // Its old committed owner remains intact through the final accepted C beat.
    private val captureOwner = if (futureWayReservation) Mux(capturing, captureEntry, 0.U) else 0.U
    private val captureLive = if (futureWayReservation) capturing && releasePhases(captureOwner) === rCapture else false.B
    private val capturedDirectory = if (futureWayReservation)
        Mux(captureLive, releaseDirectories(captureOwner), 0.U) else 0.U(directoryBits.W)
    private val capturedAddress = if (futureWayReservation)
        Mux(captureLive, releaseAddresses(captureOwner), 0.U) else 0.U(64.W)
    private val futurePaired = VecInit((0 until acquireEntries).map(i =>
        if (futureWayReservation) active(i) && captureLive && directory(i) === capturedDirectory else false.B))
    private def futureDirectoryAvailable(address: UInt, way: Int): Bool = {
        val slot = waySlot(address, way)
        // canAcquire retains the full-PA releaseSet veto, including this capture.
        // Reuse that check rather than select/compare another full-width address.
        if (futureWayReservation) captureLive && capturedDirectory === slot && owned(slot) &&
            !directoryReserved(slot)
        else false.B
    }
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
        releasePhases(i) =/= rIdle && releaseSources(i) === port.c.bits.source && releaseClients(i) === cClient).reduce(_ || _)
    // A remains set-serialized through E. Only a complete dirty victim may
    // start C beside a distinct transient line; its committed directory owner
    // is checked below, outside C.ready's functional tag-read cone.
    private val distinctRelease = if (distinctWayRelease || memoryScheduleOverlap)
        port.c.bits.opcode === TLOpcode.ReleaseData && !(0 until acquireEntries).map(i =>
            active(i) && addresses(i)(63, 6) === port.c.bits.address(63, 6)).reduce(_ || _)
    else false.B
    // A competing Acquire reserves the old slot while its owner may race the
    // probe with a voluntary Release. That C must be allowed to make progress.
    private val racingRelease = if (nClients > 1) (0 until acquireEntries).map(i =>
        phase(i) === probing && addresses(i)(63, 6) === port.c.bits.address(63, 6)).reduce(_ || _)
    else false.B
    cLocked := capturing || probeCActive
    private val releaseReady = !probeCActive && (capturing ||
        (releaseFree.asUInt.orR && (!transientSet(port.c.bits.address) || distinctRelease || racingRelease) &&
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
                lineOwned(port.c.bits.address, releaseTags) &&
                ownerClients(ownedSlot(port.c.bits.address, releaseTags)) === cClient,
                "release has no matching committed client owner")
            if (distinctWayRelease || memoryScheduleOverlap) {
                for (i <- 0 until acquireEntries) {
                    when(active(i)) {
                        assert(addresses(i)(63, 6) =/= port.c.bits.address(63, 6) &&
                            directory(i) =/= ownedSlot(port.c.bits.address, releaseTags),
                            "first release C aliases a transient line or reserved directory slot")
                    }
                }
            }
            captureEntry := newRelease
            releaseAddresses(newRelease) := port.c.bits.address
            releaseSources(newRelease) := port.c.bits.source
            releaseClients(newRelease) := cClient
            releaseDirectories(newRelease) := ownedSlot(port.c.bits.address, releaseTags)
            releaseData(newRelease)(0) := port.c.bits.data
            releaseBeat := 1.U
            when(port.c.bits.opcode === TLOpcode.ReleaseData) {
                releasePhases(newRelease) := rCapture; capturing := true.B
            }.otherwise { clearOwned(ownedSlot(port.c.bits.address, releaseTags), 0); releasePhases(newRelease) := rAck }
        }.otherwise {
            assert(releasePhase === rCapture && port.c.bits.opcode === TLOpcode.ReleaseData &&
                port.c.bits.address === releaseAddresses(captureSlot) && port.c.bits.source === releaseSources(captureSlot) &&
                cClient === releaseClients(captureSlot),
                "release burst changed address/source/opcode")
            releaseData(captureSlot)(releaseBeat) := port.c.bits.data
            when(releaseBeat === 7.U) {
                releasePhases(captureSlot) := rSend; capturing := false.B
                if (mixedReadWrite) clearOwned(releaseDirectories(captureSlot), 1)
            }
                .otherwise { releaseBeat := releaseBeat + 1.U }
        }
    }
    when(port.c.valid && capturing) {
        assert(isRelease, "probe C interleaved a release burst")
    }
    if (distinctWayRelease || memoryScheduleOverlap) {
        // owned is a Reg Vec. Last C and E may write different full slots on
        // one edge. A pending WB's saved directory is historical after last C.
        when(capturing) {
            assert(owned(releaseDirectories(captureEntry)), "captured release lost committed directory owner")
            for (i <- 0 until acquireEntries) {
                when(active(i)) {
                    if (futureWayReservation) {
                        assert((directory(i) =/= releaseDirectories(captureEntry) || futurePaired(i)) &&
                            addresses(i)(63, 6) =/= releaseAddresses(captureEntry)(63, 6),
                            "captured release aliases an unrelated transient directory reservation")
                    } else {
                        assert(directory(i) =/= releaseDirectories(captureEntry) &&
                            addresses(i)(63, 6) =/= releaseAddresses(captureEntry)(63, 6),
                            "captured release aliases a transient directory reservation")
                    }
                }
            }
        }
        for (i <- 0 until acquireEntries) {
            when(active(i)) {
                if (futureWayReservation) {
                    // Only the exact registered capture may overlap a reservation.
                    // waitE remains unowned during first-C/E tag-bank lookup.
                    assert(!owned(directory(i)) || futurePaired(i),
                        "active Acquire reserved an unrelated committed directory slot")
                } else {
                    // Also masks the E destination's tag bank during first-C/E:
                    // an undefined read of that unowned bank cannot create a hit.
                    assert(!owned(directory(i)), "active Acquire reserved a committed directory slot")
                }
            }
        }
    }
    if (futureWayReservation) {
        val captureMask = VecInit(releasePhases.map(_ === rCapture))
        assert(PopCount(captureMask) === Mux(capturing, 1.U, 0.U),
            "release capture phase lost its unique registered owner")
        when(capturing) {
            assert(captureEntry < writebackEntries.U && captureLive && releaseBeat =/= 0.U,
                "future reservation requires an accepted dirty capture")
            assert(capturedDirectory(setBits - 1, 0) === setOf(capturedAddress),
                "captured release directory lost its saved set")
        }
        assert(PopCount(futurePaired) <= 1.U, "multiple Acquires reserved one future directory")
        for (i <- 0 until acquireEntries) {
            when(futurePaired(i)) {
                assert(owned(capturedDirectory) && addresses(i)(63, 6) =/= capturedAddress(63, 6) &&
                    directory(i)(setBits - 1, 0) === setOf(addresses(i)),
                    "future reservation lost its exact distinct-line committed owner")
                assert(phase(i) === queued || phase(i) === filling || phase(i) === grantReady,
                    "future reservation published before dirty capture completed")
            }
            when(phase(i) === waitE) {
                assert(!futurePaired(i) && !owned(directory(i)),
                    "GrantAck wait overlaps a committed or capturing directory")
            }
        }
    }

    // Ordinary direct reads retain the old ordered downstream protocol. A pending
    // upstream request prevents an endless Acquire stream from starving DMA.
    private val Seq(mIdle, mProbeSend, mProbeWait, mWriteSend, mWriteWait, mAccessSend, mAccessWait,
        mLineReadSend, mLineReadWait, mLineWriteSend, mLineWriteWait, mLineResponse, mLineHazard, mAcquireQueue) = Enum(14)
    private val maintenance = RegInit(mIdle)
    private val access = Reg(new DataRequest)
    private val maintenanceForAcquire = RegInit(false.B)
    private val maintenanceAcquire = Reg(UInt(entryBits.W))
    private val maintenanceClient = Reg(UInt(clientBits.W))
    private val lineAccess = if (dmaLineTransfers) RegInit(false.B) else WireDefault(false.B)
    private val lineWriteData = if (dmaLineTransfers) Some(Reg(UInt(512.W))) else None
    private val lineError = if (dmaLineTransfers) Some(RegInit(false.B)) else None
    private val linePending = io.dmaLine.map(_.request.valid).getOrElse(false.B)
    private val selectLine = WireDefault(false.B)
    private val anyDmaLine = WireDefault(false.B)
    private val accessSend = Mux(maintenanceForAcquire, mAcquireQueue,
        Mux(lineAccess, Mux(access.write, mLineWriteSend, mLineReadSend), mAccessSend))
    // Both selection and ownership come from registered state. Never insert
    // A.ready/fire or Release priority in this functional tag-address path.
    tagLookupAddress := Mux(maintenance === mProbeSend || maintenance === mLineHazard, access.address,
        Mux(selectLine, io.dmaLine.map(_.request.bits.address).getOrElse(0.U), io.upstream.request.bits.address))
    // All users below consume this pre-existing lookup port only when their
    // address is selected. Release and Acquire keep their independent queries.
    private val selectedLookupHits = if (sharedLookupMatch)
        Some((0 until trackedWays).map(wayHit(tagLookupAddress, _, lookupTags))) else None
    private val selectedLookupOwned = selectedLookupHits.map(_.reduce(_ || _))
    private val selectedLookupSlot = selectedLookupHits.map { hits =>
        if (trackedWays == 1) waySlot(tagLookupAddress, 0)
        else if (trackedWays == 2) Mux(hits(0), waySlot(tagLookupAddress, 0), waySlot(tagLookupAddress, 1))
        else Cat(PriorityEncoder(VecInit(hits)), setOf(tagLookupAddress))
    }
    private def functionalLookupOwned(address: UInt): Bool =
        selectedLookupOwned.getOrElse(lineOwned(address, lookupTags))
    private def functionalLookupSlot(address: UInt): UInt =
        selectedLookupSlot.getOrElse(ownedSlot(address, lookupTags))
    private val maintenanceDirectory = Reg(UInt(directoryBits.W))
    private val maintenanceData = Reg(UInt(512.W))
    private val reads = RegInit(0.U(4.W))
    private val directHeld = RegInit(false.B)
    io.drainDone := maintenance === mIdle && !anyDmaLine && !anyAcquire && reads === 0.U &&
        !directHeld && !releaseBusy && !releaseOffer && !probeCActive
    private val upperWaiting = RegInit(false.B)
    private val preferAcquire = RegInit(false.B)
    when(port.a.fire) { preferAcquire := false.B }
    when(io.upstream.request.fire) { preferAcquire := true.B }
    when(io.upstream.request.valid || linePending) { upperWaiting := true.B }
    when(io.upstream.request.fire || (!io.upstream.request.valid && !linePending)) { upperWaiting := false.B }
    private val request = io.upstream.request.bits
    private val needsProbe = !io.upstreamRequestCpu && inRam(request.address) && functionalLookupOwned(request.address)
    private val needsMaintenance = request.write || needsProbe
    private val sourceBusy = (0 until acquireEntries).map(i =>
        active(i) && sources(i) === port.a.bits.source && clients(i) === aClient).reduce(_ || _)
    private val normalDirectoryAvailable = if (futureWayReservation) freeDirectory(port.a.bits.address) else false.B
    private val futureDirectory = if (futureWayReservation)
        (0 until trackedWays).map(futureDirectoryAvailable(port.a.bits.address, _)).reduce(_ || _)
    else false.B
    // Keep the existing free-way priority even when a future way also matches.
    private val selectedDirectory = if (futureWayReservation)
        Mux(normalDirectoryAvailable, freeDirectorySlot(port.a.bits.address), capturedDirectory)
    else 0.U(directoryBits.W)
    private val acquireOwned = if (nClients > 1) lineOwned(port.a.bits.address, acquireTags) else false.B
    private val acquireDirectory = if (nClients > 1) ownedSlot(port.a.bits.address, acquireTags) else 0.U
    // The optional permit is driven only by retained read owners below. All
    // existing admission, directory, arbitration and drain guards remain.
    private val dmaReadAcquirePermit = if (dmaReadAcquireOverlap) WireDefault(false.B) else false.B
    private val canAcquire = !io.drainRequest &&
        (if (dmaReadAcquireOverlap) !anyDmaLine || dmaReadAcquirePermit else !anyDmaLine) &&
        maintenance === mIdle && reads === 0.U && !directHeld &&
        ((!upperWaiting && !io.upstream.request.valid && !linePending) || preferAcquire) &&
        freeMask.asUInt.orR && fillQueue.io.enq.ready && !sourceBusy &&
        (if (memoryScheduleOverlap) !(0 until acquireEntries).map(i => active(i) &&
            addresses(i)(63, 6) === port.a.bits.address(63, 6)).reduce(_ || _) else !transientSet(port.a.bits.address)) &&
        !releaseSet(port.a.bits.address) &&
        !(releaseOffer && (if (memoryScheduleOverlap) port.c.bits.address(63, 6) === port.a.bits.address(63, 6)
            else setOf(port.c.bits.address) === setOf(port.a.bits.address))) &&
        (acquireOwned || (if (futureWayReservation) normalDirectoryAvailable || futureDirectory
            else freeDirectory(port.a.bits.address)))
    port.a.ready := canAcquire
    // Reader readiness does not affect A admission. A failed direct dispatch
    // falls back to the existing FIFO with the same reserved metadata/tag.
    directFillOffer := port.a.fire && !acquireOwned && !fillQueue.io.deq.valid && readDispatchAllowed
    fillQueue.io.enq.valid := port.a.fire && !acquireOwned && !directFillFire
    fillQueue.io.enq.bits := allocate
    when(port.a.fire) {
        assert(port.a.bits.opcode === TLOpcode.AcquireBlock && port.a.bits.param === TLPermissions.nToT &&
            port.a.bits.size === 6.U && port.a.bits.address(5, 0) === 0.U &&
            inRam(port.a.bits.address) && ((nClients > 1).B || !lineOwned(port.a.bits.address, acquireTags)) &&
            !port.a.bits.corrupt, "home accepts only an aligned nToT AcquireBlock")
        addresses(allocate) := port.a.bits.address
        sources(allocate) := port.a.bits.source
        clients(allocate) := aClient
        if (futureWayReservation) {
            assert(!directoryReserved(selectedDirectory) &&
                Mux(normalDirectoryAvailable, !owned(selectedDirectory),
                    futureDirectory && captureLive && selectedDirectory === capturedDirectory &&
                        owned(selectedDirectory) && port.a.bits.address(63, 6) =/= capturedAddress(63, 6)),
                "Acquire selected neither an ordinary free nor an exact future directory")
        }
        directory(allocate) := Mux(acquireOwned, acquireDirectory,
            (if (futureWayReservation) selectedDirectory else freeDirectorySlot(port.a.bits.address)))
        errors(allocate) := false.B
        phase(allocate) := Mux(acquireOwned, probing, Mux(directFillFire, filling, queued))
        when(acquireOwned) {
            access := 0.U.asTypeOf(new DataRequest)
            access.address := port.a.bits.address
            maintenanceDirectory := acquireDirectory
            maintenanceClient := ownerClients(acquireDirectory)
            maintenanceForAcquire := true.B
            maintenanceAcquire := allocate
            maintenance := mProbeSend
            if (dmaLineTransfers) lineAccess := false.B
        }
    }
    when(maintenance === mAcquireQueue) {
        assert(phase(maintenanceAcquire) === probing && !owned(directory(maintenanceAcquire)),
            "probe completion lost the reserved Acquire or old owner")
        fillQueue.io.enq.valid := true.B
        fillQueue.io.enq.bits := maintenanceAcquire
        when(fillQueue.io.enq.fire) {
            phase(maintenanceAcquire) := queued
            maintenance := mIdle
            maintenanceForAcquire := false.B
        }
    }
    private val lineAdmissionOpen = !io.drainRequest && maintenance === mIdle && !anyAcquire &&
        (!releaseBusy || directHeld) && (!port.a.valid || !preferAcquire) && !releaseOffer
    // The optional early capture is DMA-only. Scalar/atomic traffic retains
    // the original all-Acquire barrier; all other admission guards are shared.
    private val dmaLineAdmissionOpen = if (dmaProbeAcquireOverlap)
        !io.drainRequest && maintenance === mIdle &&
            (!releaseBusy || directHeld) && (!port.a.valid || !preferAcquire) && !releaseOffer
    else lineAdmissionOpen
    private val upperOpen = lineAdmissionOpen && !anyDmaLine
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
        maintenanceForAcquire := false.B
        maintenanceClient := ownerClients(functionalLookupSlot(request.address))
        if (dmaLineTransfers) lineAccess := false.B
        maintenanceDirectory := functionalLookupSlot(request.address)
        maintenance := Mux(needsProbe, mProbeSend, mAccessSend)
    }
    when(maintenance === mAccessSend && io.downstream.request.fire) { maintenance := mAccessWait }
    when(maintenance === mAccessWait && io.upstream.response.fire) { maintenance := mIdle }

    private val probe = Module(new TileLinkLineProbeEngine(params, entries = 2, tagBits = 1))
    port.b <> probe.io.probe
    bClient := maintenanceClient
    // A not-yet-issued probe can disappear only before entering the engine.
    // An issued probe completes after any racing voluntary ReleaseAck.
    private val probeStillOwned = functionalLookupOwned(access.address)
    probe.io.request.valid := maintenance === mProbeSend && probeStillOwned && !releaseOffer && !releaseBusy
    probe.io.request.bits.address := Cat(access.address(63, 6), 0.U(6.W))
    probe.io.request.bits.tag := 0.U
    when(maintenance === mProbeSend && !probeStillOwned && !releaseBusy) { maintenance := accessSend }
    when(probe.io.request.fire) { maintenance := mProbeWait }
    probe.io.ack.valid := port.c.valid && !isRelease && !capturing && cClient === maintenanceClient
    probe.io.ack.bits := port.c.bits
    port.c.ready := Mux(isRelease, releaseReady, !capturing && probe.io.ack.ready && cClient === maintenanceClient)
    when(port.c.valid && probeCActive) {
        assert(port.c.bits.opcode === TLOpcode.ProbeAckData && port.c.bits.source === probeCSource && cClient === cHeldClient,
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
        clearOwned(maintenanceDirectory, 2)
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
    // Offered DATA depends only on the retained maintenance owner. Completion
    // qualifies VALID/tag below, never the 512-bit payload selection fanout.
    writes.io.in(1).bits.data := (if (dmaMaintenanceCompletionFlow)
        Mux(maintenance === mWriteSend, maintenanceData, lineWriteData.get)
    else Mux(maintenance === mLineWriteSend, lineWriteData.getOrElse(0.U), maintenanceData))
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

    if (dmaLineTransfers && dmaLineEntries == 1) {
        val line = io.dmaLine.get
        val preferLine = RegInit(true.B)
        selectLine := line.request.valid && !directHeld &&
            (preferLine || !io.upstream.request.valid)
        when(io.upstream.request.fire) { preferLine := true.B }
        line.request.ready := selectLine && upperOpen && reads === 0.U
        line.response.valid := maintenance === mLineResponse
        line.response.bits.tag := 0.U
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
            maintenanceDirectory := functionalLookupSlot(line.request.bits.address)
            maintenanceClient := ownerClients(functionalLookupSlot(line.request.bits.address))
            maintenanceForAcquire := false.B
            maintenance := Mux(functionalLookupOwned(line.request.bits.address), mProbeSend,
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
    if (dmaLineTransfers && dmaLineEntries > 1) {
        val line = io.dmaLine.get
        val slotBits = log2Ceil(dmaLineEntries)
        val ownedLines = RegInit(VecInit(Seq.fill(dmaLineEntries)(false.B)))
        val lineAddresses = Reg(Vec(dmaLineEntries, UInt(64.W)))
        val lineWrites = Reg(Vec(dmaLineEntries, Bool()))
        val accessTag = Reg(UInt(slotBits.W))
        anyDmaLine := ownedLines.asUInt.orR
        if (dmaReadAcquireOverlap) {
            // Only an already-dispatched DMA read may coexist with a fresh,
            // disjoint refill. A competing committed owner would need Probe
            // maintenance and therefore keeps the original drain barrier.
            dmaReadAcquirePermit := !acquireOwned && (0 until dmaLineEntries).map(i =>
                !ownedLines(i) || (!lineWrites(i) &&
                    lineAddresses(i)(63, 6) =/= port.a.bits.address(63, 6))).reduce(_ && _)
            assert(!(port.a.fire && line.request.fire),
                "DMA and Acquire must retain exclusive admission arbitration")
        }
        val preferLine = RegInit(true.B)
        selectLine := line.request.valid && !directHeld && (preferLine || !io.upstream.request.valid)
        when(io.upstream.request.fire) { preferLine := true.B }
        // Only bounded occupancy/tag state enters admission. Address hazards
        // are resolved after capture, outside the upstream READY path.
        line.request.ready := selectLine && dmaLineAdmissionOpen && reads === 0.U &&
            !ownedLines(line.request.bits.tag)
        when(line.request.fire) {
            assert(line.request.bits.tag < dmaLineEntries.U && !ownedLines(line.request.bits.tag),
                "home line tag reused before response")
            if (dmaProbeAcquireOverlap) {
                assert(reads === 0.U && !releaseBusy && !directHeld && !maintenanceForAcquire,
                    "staged line DMA crossed a scalar, release or maintenance owner")
            } else {
                assert(!anyAcquire && reads === 0.U && !releaseBusy && !directHeld,
                    "line DMA crossed a coherence owner")
            }
            assert(line.request.bits.address(5, 0) === 0.U && inRam(line.request.bits.address) &&
                (line.request.bits.address +& 64.U) <= (base + bytes).U(65.W),
                "line DMA only accepts a complete naturally aligned RAM line")
            ownedLines(line.request.bits.tag) := true.B
            lineAddresses(line.request.bits.tag) := line.request.bits.address
            lineWrites(line.request.bits.tag) := line.request.bits.write
            accessTag := line.request.bits.tag
            access := 0.U.asTypeOf(new DataRequest)
            access.address := line.request.bits.address
            access.write := line.request.bits.write
            lineWriteData.get := line.request.bits.data
            lineAccess := true.B
            if (lineTransferDispatchFlow) {
                // Qualify only the captured offer, never upstream READY. A
                // committed owner or older same-line DMA uses the unchanged
                // registered hazard/probe path. There is still a register cut
                // between accepted line metadata and the transfer engine.
                val incomingConflict = (0 until dmaLineEntries).map(i => ownedLines(i) &&
                    lineAddresses(i)(63, 6) === line.request.bits.address(63, 6)).reduce(_ || _)
                val incomingOwned = functionalLookupOwned(line.request.bits.address)
                // An older Acquire may not have committed ownership yet.
                // Always recheck its set and the committed lookup after capture.
                maintenance := Mux(if (dmaProbeAcquireOverlap) incomingConflict || incomingOwned || anyAcquire
                    else incomingConflict || incomingOwned, mLineHazard,
                    Mux(line.request.bits.write, mLineWriteSend, mLineReadSend))
            } else maintenance := mLineHazard
            preferLine := false.B
            preferAcquire := true.B
            upperWaiting := false.B
        }
        val olderSameLine = (0 until dmaLineEntries).map(i => ownedLines(i) && accessTag =/= i.U &&
            lineAddresses(i)(63, 6) === access.address(63, 6)).reduce(_ || _)
        // In the bounded profile setOf is PA[13:6]. This check uses only
        // saved addresses, outside DMA READY and the functional tag-address mux.
        when(if (dmaProbeAcquireOverlap)
            maintenance === mLineHazard && !transientSet(access.address) &&
                !olderSameLine && !releaseBusy && !releaseOffer
        else maintenance === mLineHazard && !olderSameLine && !releaseBusy && !releaseOffer) {
            maintenanceDirectory := functionalLookupSlot(access.address)
            maintenanceClient := ownerClients(functionalLookupSlot(access.address))
            maintenanceForAcquire := false.B
            maintenance := Mux(functionalLookupOwned(access.address), mProbeSend, accessSend)
        }
        // Only the retained, successful internal dirty-writeback completion
        // may expose the dependent access. For this exact full tag the response
        // READY below is unconditional (!writeIsLine), independent of dispatch.
        // Writer response validity/tag/error are registered completion state.
        val dmaMaintenanceComplete = if (dmaMaintenanceCompletionFlow)
            transfer.io.writeResponse.fire && transfer.io.writeResponse.bits.tag === writebackEntries.U &&
                !transfer.io.writeResponse.bits.error && maintenance === mWriteWait &&
                lineAccess && !maintenanceForAcquire
        else false.B
        if (dmaMaintenanceCompletionFlow) {
            when(dmaMaintenanceComplete) {
                assert(transfer.io.writeResponse.ready && ownedLines(accessTag) && !olderSameLine,
                    "DMA maintenance completion lost its retained exclusive owner")
            }
        }
        // These accepted-dispatch assignments deliberately follow the generic
        // completion handler: acceptance wins over its accessSend fallback.
        // A queued old fill retains VALID/address/tag and its dequeue. Once
        // empty, blocked fresh A keeps the selected DMA offer stable under stall.
        when(if (dmaProbeAcquireOverlap)
            !fillQueue.io.deq.valid && (if (dmaMaintenanceCompletionFlow)
                maintenance === mLineReadSend || (dmaMaintenanceComplete && !access.write)
            else maintenance === mLineReadSend)
        else if (dmaMaintenanceCompletionFlow)
            maintenance === mLineReadSend || (dmaMaintenanceComplete && !access.write)
        else maintenance === mLineReadSend) {
            if (dmaProbeAcquireOverlap) {
                assert(!fillQueue.io.deq.valid && ownedLines(accessTag) && lineAccess && !maintenanceForAcquire,
                    "staged DMA read lost its retained owner or overwrote a queued fill")
            } else {
                assert(!fillQueue.io.deq.valid && !anyAcquire && ownedLines(accessTag),
                    "pipelined DMA read lost exclusive admission")
            }
            transfer.io.readRequest.valid := true.B
            transfer.io.readRequest.bits.address := access.address
            transfer.io.readRequest.bits.tag := acquireEntries.U(writeTagBits.W) + accessTag
            when(transfer.io.readRequest.fire) {
                assert(transfer.io.readRequest.bits.tag >= acquireEntries.U &&
                    transfer.io.readRequest.bits.tag < (acquireEntries + dmaLineEntries).U && !lineWrites(accessTag),
                    "DMA read tag overlaps refill tag class")
                maintenance := mIdle; lineAccess := false.B
            }
        }
        when(if (dmaMaintenanceCompletionFlow)
            maintenance === mLineWriteSend || (dmaMaintenanceComplete && access.write)
        else maintenance === mLineWriteSend) {
            if (dmaMaintenanceCompletionFlow) {
                // Still input 1 of the original RR/queue dispatch, never a
                // bypass of Release arbitration or writer capacity. A blocked
                // completion-edge offer falls into mLineWriteSend unchanged.
                writes.io.in(1).valid := true.B
            }
            writes.io.in(1).bits.tag := (writebackEntries + 1).U(writeTagBits.W) + accessTag
            when(writes.io.in(1).fire) {
                assert(writes.io.in(1).bits.tag > writebackEntries.U &&
                    writes.io.in(1).bits.tag < (writebackEntries + 1 + dmaLineEntries).U && lineWrites(accessTag),
                    "DMA write tag overlaps release/probe tag class")
                maintenance := mIdle; lineAccess := false.B
            }
        }
        val readIsLine = transfer.io.readResponse.bits.tag >= acquireEntries.U &&
            transfer.io.readResponse.bits.tag < (acquireEntries + dmaLineEntries).U
        val writeIsLine = transfer.io.writeResponse.bits.tag > writebackEntries.U &&
            transfer.io.writeResponse.bits.tag < (writebackEntries + 1 + dmaLineEntries).U
        val readValid = transfer.io.readResponse.valid && readIsLine
        val writeValid = transfer.io.writeResponse.valid && writeIsLine
        // Engines retain their own complete payloads/metadata. Lock the chosen
        // direction under response backpressure rather than duplicate line RAM.
        val replyHeld = RegInit(false.B)
        val heldWrite = Reg(Bool())
        val preferWrite = RegInit(false.B)
        val chooseWrite = Mux(replyHeld, heldWrite, writeValid && (!readValid || preferWrite))
        val readTag = (transfer.io.readResponse.bits.tag - acquireEntries.U)(slotBits - 1, 0)
        val writeTag = (transfer.io.writeResponse.bits.tag - (writebackEntries + 1).U)(slotBits - 1, 0)
        line.response.valid := Mux(chooseWrite, writeValid, readValid)
        line.response.bits.tag := Mux(chooseWrite, writeTag, readTag)
        line.response.bits.error := Mux(chooseWrite, transfer.io.writeResponse.bits.error, transfer.io.readResponse.bits.error)
        line.response.bits.data := Mux(chooseWrite || line.response.bits.error, 0.U, transfer.io.readResponse.bits.data)
        transfer.io.readResponse.ready := !readIsLine || (!chooseWrite && line.response.ready)
        transfer.io.writeResponse.ready := !writeIsLine || (chooseWrite && line.response.ready)
        when(line.response.valid && !line.response.ready) { replyHeld := true.B; heldWrite := chooseWrite }
        when(line.response.fire) {
            val tag = line.response.bits.tag
            assert(ownedLines(tag) && lineWrites(tag) === chooseWrite,
                "home line response lost read/write owner")
            ownedLines(tag) := false.B
            replyHeld := false.B
            preferWrite := !chooseWrite
        }
        if (dmaProbeAcquireOverlap) {
            when(lineAccess) {
                assert(ownedLines(accessTag) && maintenance =/= mIdle && !maintenanceForAcquire,
                    "staged DMA maintenance lost its pending tag")
            }
            when(port.a.fire && anyDmaLine) {
                assert((0 until dmaLineEntries).map(i => !ownedLines(i) || !lineWrites(i)).reduce(_ && _),
                    "fresh Acquire crossed a live DMA write")
            }
        }
        when(anyDmaLine) {
            if (dmaReadAcquireOverlap) {
                assert(reads === 0.U && !directHeld, "live DMA line crossed scalar owner")
                when(anyAcquire) {
                    if (dmaProbeAcquireOverlap) {
                        assert(!maintenanceForAcquire,
                            "staged DMA overlap crossed Acquire maintenance ownership")
                    } else {
                        assert(maintenance === mIdle && !lineAccess && !maintenanceForAcquire,
                            "DMA read/Acquire overlap crossed maintenance ownership")
                    }
                    for (i <- 0 until dmaLineEntries) {
                        when(ownedLines(i)) {
                            if (!dmaProbeAcquireOverlap)
                                assert(!lineWrites(i), "DMA write crossed an Acquire owner")
                            for (j <- 0 until acquireEntries) {
                                when(active(j)) {
                                    if (dmaProbeAcquireOverlap) {
                                        when(lineAccess && accessTag === i.U) {
                                            // Only the parked captured owner may alias an old
                                            // Acquire. Progressed maintenance is different-set.
                                            when(maintenance =/= mLineHazard) {
                                                assert(setOf(lineAddresses(i)) =/= setOf(addresses(j)),
                                                    "progressed DMA maintenance shares an Acquire set")
                                            }
                                        }.otherwise {
                                            // Keep the existing read-first same-set/different-line
                                            // case and permit an old Acquire beside a dispatched write.
                                            assert(lineAddresses(i)(63, 6) =/= addresses(j)(63, 6),
                                                "dispatched DMA and Acquire own the same physical line")
                                        }
                                    } else {
                                        assert(lineAddresses(i)(63, 6) =/= addresses(j)(63, 6),
                                            "DMA read and Acquire own the same physical line")
                                    }
                                }
                            }
                        }
                    }
                }
            } else {
                assert(!anyAcquire && reads === 0.U && !directHeld,
                    "live DMA line crossed refill or scalar owner")
            }
        }
    }
    when(transfer.io.readResponse.fire) {
        assert(transfer.io.readResponse.bits.tag < (acquireEntries + (if (dmaLineTransfers) dmaLineEntries else 0)).U,
            "home read result has an unknown full tag")
    }
    when(transfer.io.writeResponse.fire) {
        assert(transfer.io.writeResponse.bits.tag < (writebackEntries + (if (dmaLineTransfers) dmaLineEntries + 1 else 1)).U,
            "home write result has an unknown full tag")
    }

    private val independentLineGrant = internalLineGrant && nClients > 1
    private val lineGrantLocked = if (independentLineGrant) RegInit(false.B) else WireDefault(false.B)
    private val lineGrantEntry = if (independentLineGrant) Reg(UInt(entryBits.W)) else WireDefault(0.U(entryBits.W))
    private val dLocked = RegInit(false.B)
    private val dRelease = Reg(Bool())
    private val dEntry = Reg(UInt(entryBits.W))
    private val dBeat = RegInit(0.U(3.W))
    private val dTurn = RegInit(0.U(entryBits.W))
    if (futureWayReservation) {
        when(dLocked && !dRelease) {
            assert(!futurePaired(dEntry), "incomplete future way seized the held Grant owner")
        }
    }
    // Exclude an incomplete future way before arbitration and the held D owner.
    // A fast refill must not lock out an eligible Grant or the old ReleaseAck.
    private val grantMask = if (futureWayReservation)
        VecInit((0 until acquireEntries).map(i => phase(i) === grantReady && !futurePaired(i)))
    else VecInit(phase.map(_ === grantReady))
    private val afterTurn = VecInit((0 until acquireEntries).map(i => grantMask(i) && i.U >= dTurn))
    private val selectedGrant = Mux(afterTurn.asUInt.orR, PriorityEncoder(afterTurn), PriorityEncoder(grantMask))
    private val releaseAckMask = VecInit(releasePhases.map(_ === rAck))
    private val heldRelease = Reg(UInt(releaseBits.W))
    private val ackRelease = Mux(dLocked, heldRelease, PriorityEncoder(releaseAckMask))
    private val sendRelease = if (independentLineGrant) true.B
        else Mux(dLocked, dRelease, releaseAckMask.asUInt.orR)
    private val grantEntry = if (independentLineGrant) Mux(lineGrantLocked, lineGrantEntry, selectedGrant)
        else Mux(dLocked, dEntry, selectedGrant)
    dClient := Mux(sendRelease, releaseClients(ackRelease), clients(grantEntry))
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
    private val grantFire = if (independentLineGrant) {
        // Whole-line Grant and standard D ReleaseAck are separate channels.
        // Each locks its own owner so a held Grant cannot block a racing Release.
        for (i <- 0 until nClients) {
            val grant = io.lineGrants.get(i)
            grant.valid := grantMask(grantEntry) && clients(grantEntry) === i.U
            grant.bits.source := sources(grantEntry)
            grant.bits.sink := grantEntry
            grant.bits.cap := TLPermissions.toT
            grant.bits.denied := errors(grantEntry)
            grant.bits.corrupt := errors(grantEntry)
            grant.bits.data := Mux(errors(grantEntry), 0.U, data(grantEntry).asUInt)
        }
        when(grantMask(grantEntry) && !lineGrantLocked) {
            lineGrantLocked := true.B
            lineGrantEntry := grantEntry
        }
        when(port.d.valid && !dLocked) { dLocked := true.B; heldRelease := ackRelease }
        io.lineGrants.get.map(_.fire).reduce(_ || _)
    } else if (internalLineGrant) {
        val grant = io.lineGrants.get(0)
        // Preserve the shared arbitration/held-owner cut. ReleaseAck stays on
        // standard D; a data Grant uses exactly one of the two transports.
        port.d.valid := sendRelease && releaseAckMask(ackRelease)
        grant.valid := !sendRelease && grantMask(grantEntry)
        grant.bits.source := sources(grantEntry)
        grant.bits.sink := grantEntry
        grant.bits.cap := TLPermissions.toT
        grant.bits.denied := errors(grantEntry)
        grant.bits.corrupt := errors(grantEntry)
        grant.bits.data := Mux(errors(grantEntry), 0.U, data(grantEntry).asUInt)
        when((port.d.valid || grant.valid) && !dLocked) {
            dLocked := true.B; dRelease := sendRelease; dEntry := grantEntry; heldRelease := ackRelease
        }
        grant.fire
    } else {
        when(port.d.valid && !dLocked) { dLocked := true.B; dRelease := sendRelease; dEntry := grantEntry; heldRelease := ackRelease }
        port.d.fire && !sendRelease
    }
    when(port.d.fire) {
        when(sendRelease) {
            releaseRetired := true.B
            releasePhases(ackRelease) := rIdle
            dLocked := false.B
        }
    }
    when(grantFire) {
        if (futureWayReservation) assert(!futurePaired(grantEntry), "Grant published an incomplete future way")
        when(internalLineGrant.B || dBeat === 7.U) {
            phase(grantEntry) := waitE
            dBeat := 0.U
            dTurn := grantEntry + 1.U
            if (independentLineGrant) lineGrantLocked := false.B else dLocked := false.B
        }.otherwise { dBeat := dBeat + 1.U }
    }
    private val eInRange = port.e.bits.sink < acquireEntries.U
    private val eEntry = port.e.bits.sink(entryBits - 1, 0)
    port.e.ready := eInRange && phase(eEntry) === waitE && clients(eEntry) === eClient
    when(port.e.valid) {
        assert(eInRange && active(eEntry) && clients(eEntry) === eClient, "GrantAck has no live sink or matching client")
    }
    when(port.e.fire) {
        if (futureWayReservation) {
            assert(!futurePaired(eEntry) && !owned(directory(eEntry)),
                "GrantAck overlaps a committed or capturing directory")
        }
        when(!errors(eEntry)) {
            assert(!owned(directory(eEntry)), "reserved directory slot changed before GrantAck")
            if (tagConfig.compact) assert(tagGeometry.contains(addresses(eEntry)), "home tag outside aperture")
            assert(directory(eEntry)(setBits - 1, 0) === setOf(addresses(eEntry)),
                "GrantAck directory index lost its reserved set")
            for (way <- 0 until trackedWays) {
                val selectedWay = if (trackedWays == 1) true.B else directory(eEntry)(directoryBits - 1, setBits) === way.U
                when(selectedWay) {
                    tagBanks(way).write(directory(eEntry)(setBits - 1, 0), tagGeometry.tag(addresses(eEntry)))
                }
            }
            if (dmaReadAcquireOverlap) {
                ownedSetValid := true.B
                ownedSetSlot := directory(eEntry)
            } else owned(directory(eEntry)) := true.B
            ownerClients(directory(eEntry)) := eClient
        }
        phase(eEntry) := free
    }
    if (nClients > 1) {
        for (i <- 0 until acquireEntries) {
            when(active(i) && owned(directory(i))) {
                assert(phase(i) === probing && maintenanceForAcquire && maintenanceAcquire === i.U,
                    "live Acquire aliases an unrelated committed directory owner")
            }
        }
        when(maintenanceForAcquire) {
            assert(phase(maintenanceAcquire) === probing,
                "Acquire probe context outlived its reserved owner")
        }
    }
    for (i <- 0 until acquireEntries; j <- i + 1 until acquireEntries) {
        when(active(i) && active(j)) {
            assert(clients(i) =/= clients(j) || sources(i) =/= sources(j), "duplicate live Acquire client/source")
            if (memoryScheduleOverlap) {
                assert(addresses(i)(63, 6) =/= addresses(j)(63, 6), "duplicate transient physical line")
            } else assert(setOf(addresses(i)) =/= setOf(addresses(j)), "overlapping transient cache sets")
            assert(directory(i) =/= directory(j), "duplicate reserved directory slot")
        }
    }
}
