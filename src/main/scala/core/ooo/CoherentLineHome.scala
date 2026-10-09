package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLBundle, TLOpcode, TLParams, TLPermissions}
import soc.ip.tilelink.{TileLinkLineProbeEngine, TileLinkLineTransfer}

/** Shared structural interface; the legacy and bounded concurrent homes remain separate implementations. */
class CoherentLineHomeIO(params: TLParams, nClients: Int, dmaLineTransfers: Boolean = false) extends Bundle {
    val dmaLine = if (dmaLineTransfers) Some(Flipped(new soc.ip.dma.DmaLinePort)) else None
    val upstream = Flipped(new DataPort)
    val downstream = new DataPort
    val clients = Vec(nClients, Flipped(new TLBundle(params)))
    val line = new TLBundle(params)
    val upstreamRequestCpu = Input(Bool())
    // Assert only after the cache-local flush has quiesced its own producers.
    // New A/upstream admissions close; accepted owners and irrevocable offers drain.
    val drainRequest = Input(Bool())
    val drainDone = Output(Bool())
}

abstract class CoherentLineHomeModule(params: TLParams, nClients: Int, dmaLineTransfers: Boolean = false) extends Module {
    val io = IO(new CoherentLineHomeIO(params, nClients, dmaLineTransfers))
}

object CoherentLineHomeModule {
    def build(
        params: TLParams,
        base: BigInt,
        bytes: BigInt,
        nClients: Int = 1,
        trackedLines: Int = 0,
        trackedWays: Int = 1,
        acquireEntries: Int = 1,
        rawResponseMetadata: Boolean = false,
        parallelQualification: Boolean = false,
        tagConfig: CacheTagConfig = CacheTagConfig.FullWidth,
        writebackEntries: Int = 1,
        mixedReadWrite: Boolean = false,
        dmaLineTransfers: Boolean = false
    ): CoherentLineHomeModule = {
        require(!dmaLineTransfers || (acquireEntries > 1 && (writebackEntries > 1 || mixedReadWrite)),
            "line DMA requires the bounded mixed coherence home")
        require(Set(1, 2, 4).contains(acquireEntries))
        require(acquireEntries > 1 || writebackEntries == 1)
        if (acquireEntries == 1) Module(new CoherentLineHome(params, base, bytes, nClients,
            trackedLines, trackedWays, rawResponseMetadata, parallelQualification, tagConfig))
        else {
            require(nClients == 1 && trackedLines > 0,
                "bounded concurrent home currently requires one client and an explicit directory capacity")
            if (writebackEntries > 1 || mixedReadWrite)
                Module(new MixedCoherentLineHome(params, base, bytes, trackedLines,
                    trackedWays, acquireEntries, rawResponseMetadata, tagConfig, writebackEntries, mixedReadWrite, dmaLineTransfers))
            else Module(new NonBlockingCoherentLineHome(params, base, bytes, trackedLines,
                trackedWays, acquireEntries, rawResponseMetadata, tagConfig))
        }
    }
}

/** Serialized TL-C home for private T owners. A line has at most one owner; a competing
  * client or uncached agent probes that owner before accessing backing RAM. The client
  * count is explicit so source IDs and probe/GrantAck routing remain local to each hart.
  */
class CoherentLineHome(
    params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
    base: BigInt = BigInt("80010000", 16),
    bytes: BigInt = 4096,
    nClients: Int = 1,
    trackedLines: Int = 0,
    trackedWays: Int = 1,
    rawResponseMetadata: Boolean = false,
    parallelQualification: Boolean = false,
    tagConfig: CacheTagConfig = CacheTagConfig.FullWidth
) extends CoherentLineHomeModule(params, nClients) {
    require(bytes >= 64 && bytes % 64 == 0 && isPow2(bytes) && base % 64 == 0)
    require(nClients >= 1 && nClients <= 8)
    require(trackedLines == 0 || (nClients == 1 && trackedLines >= 2 &&
        trackedLines <= bytes / 64 && isPow2(trackedLines)))
    require(trackedLines != 0 || base % bytes == 0)
    require(Set(1, 2).contains(trackedWays) &&
        (trackedWays == 1 || (trackedLines != 0 && trackedLines / trackedWays >= 2)))
    require(params.sourceBits >= 3, "line transfer needs separate read and write source IDs")
    private def client(index: UInt): TLBundle = if (nClients == 1) io.clients(0) else io.clients(index)
    private val clientBits = math.max(1, log2Ceil(nClients))
    private val Seq(idle, probeSend, probeWait, accessSend, accessWait, fillSend, fillWait,
        grant, grantAck, releaseReceive, lineWriteSend, lineWriteWait, releaseAck) = Enum(13)
    private val state = RegInit(idle)
    private val resume = Reg(UInt(state.getWidth.W))
    private val reads = RegInit(0.U(4.W))
    private val access = Reg(new DataRequest)
    private val acquireAddress = Reg(UInt(params.addrWidth.W))
    private val acquireSource = Reg(UInt(params.sourceBits.W))
    private val acquireClient = Reg(UInt(clientBits.W))
    private val probeAddress = Reg(UInt(params.addrWidth.W))
    private val probeClient = Reg(UInt(clientBits.W))
    private val probeForAcquire = Reg(Bool())
    private val lineAddress = Reg(UInt(params.addrWidth.W))
    private val lineData = Reg(Vec(8, UInt(64.W)))
    private val lineError = Reg(Bool())
    private val beat = RegInit(0.U(3.W))
    private val releaseSource = Reg(UInt(params.sourceBits.W))
    private val releaseClient = Reg(UInt(clientBits.W))
    private val releaseParam = Reg(UInt(3.W))
    private val releaseOrigin = Reg(Bool())
    private val ownerEntries = if (trackedLines == 0) (bytes / 64).toInt else trackedLines
    private val owned = RegInit(VecInit(Seq.fill(ownerEntries)(false.B)))
    private val owner = Reg(Vec(ownerEntries, UInt(clientBits.W)))
    // A single L1 owns at most trackedWays physical lines per cache set.
    // Directory slots need not use the client's physical way number: tag lookup
    // finds owners, and a completed GrantAck reserves an empty slot in that set.
    // Capacity stays bounded by L1 capacity rather than external RAM size.
    private val tagGeometry = tagConfig.geometry(base, bytes, 6, params.addrWidth)
    private val ownedTags = if (trackedLines == 0) None else
        Some(Reg(Vec(ownerEntries, UInt(tagGeometry.tagBits.W))))
    private val lineTransfer = Module(new TileLinkLineTransfer(
        params.copy(sourceBits = params.sourceBits - 1), entries = 4,
        rawResponseMetadata = rawResponseMetadata))
    private val probeEngine = Module(new TileLinkLineProbeEngine(params, entries = 4))
    io.line <> lineTransfer.io.tl
    for (i <- 0 until nClients) {
        io.clients(i).b.valid := probeEngine.io.probe.valid && probeClient === i.U
        io.clients(i).b.bits := probeEngine.io.probe.bits
    }
    probeEngine.io.probe.ready := client(probeClient).b.ready

    private val aValid = VecInit(io.clients.map(_.a.valid))
    private val aAny = aValid.asUInt.orR
    private val aTurn = RegInit(0.U(clientBits.W))
    private val afterTurn = VecInit((0 until nClients).map(i => aValid(i) && i.U >= aTurn))
    private val aSelect = Wire(UInt(clientBits.W))
    aSelect := Mux(afterTurn.asUInt.orR, PriorityEncoder(afterTurn), PriorityEncoder(aValid))
    private val releaseValid = VecInit(io.clients.map(c =>
        c.c.valid && TLOpcode.isRelease(c.c.bits.opcode)))
    private val releaseAny = releaseValid.asUInt.orR
    private val releaseSelect = Wire(UInt(clientBits.W))
    releaseSelect := PriorityEncoder(releaseValid)
    private val cSelect = Mux(state === releaseReceive, releaseClient,
        Mux(releaseAny, releaseSelect, probeClient))
    private val clientC = client(cSelect).c

    private val ownerSetBits = log2Ceil(ownerEntries / trackedWays)
    private def lineIndex(address: UInt): UInt = {
        val set = address(5 + ownerSetBits, 6)
        if (trackedWays == 1) set
        else {
            val first = Cat(0.U(1.W), set)
            val second = Cat(1.U(1.W), set)
            val tag = tagGeometry.tag(address)
            Mux(tagGeometry.qualifies(address) && owned(first) && ownedTags.get(first) === tag, first,
                Mux(tagGeometry.qualifies(address) && owned(second) && ownedTags.get(second) === tag, second,
                    Mux(!owned(first), first, second)))
        }
    }
    private def lineOwned(address: UInt): Bool = {
        if (parallelQualification && trackedLines != 0) {
            // Compare each way before owner selection. The old form selected a
            // matching slot and then compared its selected tag a second time.
            val set = address(5 + ownerSetBits, 6)
            val first = if (trackedWays == 1) set else Cat(0.U(1.W), set)
            val second = if (trackedWays == 1) first else Cat(1.U(1.W), set)
            val matches = Module(new ParallelHomeLineMatch(params.addrWidth))
            matches.io.address := address
            matches.io.firstOwned := tagGeometry.qualifies(address) && owned(first)
            matches.io.firstTag := ownedTags.get(first)
            matches.io.secondOwned := tagGeometry.qualifies(address) && (if (trackedWays == 2) owned(second) else false.B)
            matches.io.secondTag := ownedTags.get(second)
            matches.io.owned
        } else tagGeometry.qualifies(address) && owned(lineIndex(address)) &&
            ownedTags.map(_(lineIndex(address)) === tagGeometry.tag(address)).getOrElse(true.B)
    }
    private def inRam(address: UInt): Bool =
        if (parallelQualification) HomeRamRange.contains(address, params.addrWidth, base, bytes)
        else address >= base.U(65.W) && address < (base + bytes).U(65.W)
    private val request = io.upstream.request.bits
    // An ordinary read is offered combinationally to the downstream TL bridge.
    // Once stalled, it cannot be preempted by a later Acquire or voluntary C
    // release: the shared TL arbiter may already have locked this A producer.
    // Withdrawing that offer and waiting for a line fill deadlocks both paths.
    // The upstream request FIFO retains its head/payload until the same fire.
    private val directReadHeld = RegInit(false.B)
    io.drainDone := state === idle && reads === 0.U && !directReadHeld && !releaseAny
    private val releaseAllowed = reads === 0.U && !directReadHeld &&
        (state === idle || state === probeSend || state === probeWait)
    private val needsProbe = !io.upstreamRequestCpu && inRam(request.address) &&
        lineOwned(request.address)
    private val upperWrite = io.upstream.request.valid && request.write
    private val directRead = state === idle && io.upstream.request.valid && !upperWrite &&
        !needsProbe && (directReadHeld || (!io.drainRequest && !aAny && !releaseAny))

    io.downstream.request.valid := directRead || state === accessSend
    io.downstream.request.bits := Mux(state === accessSend, access, request)
    io.upstream.request.ready := state === idle && (directReadHeld || (!io.drainRequest && !aAny && !releaseAny)) &&
        Mux(upperWrite || needsProbe, reads === 0.U, io.downstream.request.ready)
    io.upstream.response.valid := Mux(state === accessWait, io.downstream.response.valid,
        state === idle && reads =/= 0.U && io.downstream.response.valid)
    io.upstream.response.bits := io.downstream.response.bits
    io.downstream.response.ready := io.upstream.response.ready &&
        (state === accessWait || (state === idle && reads =/= 0.U))
    when(directRead && !io.downstream.request.ready) { directReadHeld := true.B }
    when(directRead && io.downstream.request.fire) { directReadHeld := false.B }
    when(directReadHeld) {
        assert(state === idle && io.upstream.request.valid && !upperWrite && !needsProbe,
            "a stalled home direct read must retain its request until acceptance")
    }
    when((io.upstream.request.fire && !upperWrite && !needsProbe) =/=
        (state === idle && io.upstream.response.fire)) {
        reads := Mux(io.upstream.request.fire && !upperWrite && !needsProbe, reads + 1.U, reads - 1.U)
    }
    when(state === idle && io.upstream.request.fire && (upperWrite || needsProbe)) {
        access := request
        when(needsProbe) {
            probeAddress := Cat(request.address(63, 6), 0.U(6.W))
            probeClient := owner(lineIndex(request.address))
            probeForAcquire := false.B
        }
        state := Mux(needsProbe, probeSend, accessSend)
    }
    when(state === accessSend && io.downstream.request.fire) { state := accessWait }
    when(state === accessWait && io.upstream.response.fire) { state := idle }

    for (i <- 0 until nClients) {
        io.clients(i).a.ready := !io.drainRequest && state === idle && reads === 0.U && !releaseAny && !directReadHeld &&
            aSelect === i.U
    }
    val selectedAcquire = client(aSelect).a.bits
    val acquireFire = aAny && client(aSelect).a.fire
    val immediateFill = acquireFire && !lineOwned(selectedAcquire.address)
    when(acquireFire) {
        val a = selectedAcquire
        aTurn := Mux(aSelect === (nClients - 1).U, 0.U, aSelect + 1.U)
        assert(a.opcode === TLOpcode.AcquireBlock &&
            a.param === TLPermissions.nToT && a.size === 6.U &&
            a.address(5, 0) === 0.U && inRam(a.address) &&
            (!lineOwned(a.address) || owner(lineIndex(a.address)) =/= aSelect),
            "home accepts an aligned nToT AcquireBlock from a non-owner")
        acquireAddress := a.address
        acquireSource := a.source
        acquireClient := aSelect
        when(lineOwned(a.address)) {
            probeAddress := a.address
            probeClient := owner(lineIndex(a.address))
            probeForAcquire := true.B
            state := probeSend
        }.otherwise { state := Mux(lineTransfer.io.readRequest.ready, fillWait, fillSend) }
    }
    // A no-probe Acquire can reserve the line reader in its acceptance cycle.
    // If the reader is full, fillSend keeps the registered address stable until it opens.
    lineTransfer.io.readRequest.valid := state === fillSend || immediateFill
    lineTransfer.io.readRequest.bits.address := Mux(state === fillSend, acquireAddress,
        selectedAcquire.address)
    lineTransfer.io.readRequest.bits.tag := 0.U
    when(lineTransfer.io.readRequest.fire) { state := fillWait }
    lineTransfer.io.readResponse.ready := state === fillWait
    when(lineTransfer.io.readResponse.fire) {
        for (i <- 0 until 8) {
            lineData(i) := lineTransfer.io.readResponse.bits.data(64 * i + 63, 64 * i)
        }
        lineError := lineTransfer.io.readResponse.bits.error
        beat := 0.U
        state := grant
    }
    private val dClient = Mux(state === releaseAck, releaseClient, acquireClient)
    for (i <- 0 until nClients) {
        io.clients(i).d.valid := (state === grant || state === releaseAck) && dClient === i.U
        io.clients(i).d.bits := 0.U.asTypeOf(io.clients(i).d.bits)
        io.clients(i).d.bits.opcode := Mux(state === releaseAck, TLOpcode.ReleaseAck, TLOpcode.GrantData)
        io.clients(i).d.bits.param := Mux(state === releaseAck, 0.U, TLPermissions.toT)
        io.clients(i).d.bits.size := 6.U
        io.clients(i).d.bits.source := Mux(state === releaseAck, releaseSource, acquireSource)
        io.clients(i).d.bits.sink := 0.U
        io.clients(i).d.bits.denied := state === grant && lineError
        io.clients(i).d.bits.data := lineData(beat)
        io.clients(i).d.bits.corrupt := state === grant && lineError
    }
    when(client(dClient).d.fire && state === grant) {
        beat := beat + 1.U
        when(beat === 7.U) { state := grantAck }
    }
    for (i <- 0 until nClients) {
        io.clients(i).e.ready := state === grantAck && acquireClient === i.U
    }
    when(client(acquireClient).e.fire) {
        assert(client(acquireClient).e.bits.sink === 0.U, "line home GrantAck sink mismatch")
        when(!lineError) {
            if (trackedLines != 0) {
                assert(!owned(lineIndex(acquireAddress)) || lineOwned(acquireAddress),
                    "single-hart L1 must release a set slot before acquiring another")
                if (tagConfig.compact) assert(tagGeometry.contains(acquireAddress), "home tag outside aperture")
                ownedTags.get(lineIndex(acquireAddress)) := tagGeometry.tag(acquireAddress)
            }
            owned(lineIndex(acquireAddress)) := true.B
            owner(lineIndex(acquireAddress)) := acquireClient
        }
        state := idle
    }

    probeEngine.io.request.valid := state === probeSend && !releaseAny
    probeEngine.io.request.bits.address := probeAddress
    probeEngine.io.request.bits.tag := 0.U
    when(probeEngine.io.request.fire) { state := probeWait }
    probeEngine.io.response.ready := state === probeWait && !releaseAny
    when(probeEngine.io.response.fire) {
        assert(!probeEngine.io.response.bits.corrupt, "dirty probe data must not be corrupt")
        owned(lineIndex(probeAddress)) := false.B
        when(probeEngine.io.response.bits.hasData) {
            lineAddress := probeAddress
            for (i <- 0 until 8) {
                lineData(i) := probeEngine.io.response.bits.data(64 * i + 63, 64 * i)
            }
            lineError := false.B
            beat := 0.U
            releaseOrigin := false.B
            state := lineWriteSend
        }.otherwise { state := Mux(probeForAcquire, fillSend, accessSend) }
    }

    // C is shared by probe acknowledgements and voluntary releases. A release can preempt a
    // queued probe so a cache evicting another line can make progress without a B/C deadlock.
    val isRelease = TLOpcode.isRelease(clientC.bits.opcode)
    probeEngine.io.ack.valid := clientC.valid && !isRelease && !releaseAny
    probeEngine.io.ack.bits := clientC.bits
    for (i <- 0 until nClients) {
        io.clients(i).c.ready := cSelect === i.U &&
            Mux(isRelease, releaseAllowed || state === releaseReceive, probeEngine.io.ack.ready)
    }
    when(clientC.fire && isRelease && state =/= releaseReceive) {
        assert(releaseAllowed && clientC.bits.size === 6.U &&
            clientC.bits.address(5, 0) === 0.U && inRam(clientC.bits.address) &&
            lineOwned(clientC.bits.address) &&
            owner(lineIndex(clientC.bits.address)) === cSelect &&
            clientC.bits.param === TLPermissions.tToN,
            "invalid voluntary line release")
        releaseClient := cSelect
        releaseSource := clientC.bits.source
        releaseParam := clientC.bits.param
        lineAddress := clientC.bits.address
        lineData(0) := clientC.bits.data
        beat := 1.U
        resume := state
        when(clientC.bits.opcode === TLOpcode.ReleaseData) {
            state := releaseReceive
        }.otherwise {
            owned(lineIndex(clientC.bits.address)) := false.B
            state := releaseAck
        }
    }
    when(clientC.fire && state === releaseReceive) {
        assert(clientC.bits.opcode === TLOpcode.ReleaseData &&
            clientC.bits.address === lineAddress &&
            clientC.bits.source === releaseSource &&
            clientC.bits.param === releaseParam &&
            clientC.bits.size === 6.U && !clientC.bits.corrupt,
            "ReleaseData burst changed control or was corrupt")
        lineData(beat) := clientC.bits.data
        when(beat === 7.U) {
            beat := 0.U
            releaseOrigin := true.B
            state := lineWriteSend
        }.otherwise { beat := beat + 1.U }
    }
    lineTransfer.io.writeRequest.valid := state === lineWriteSend
    lineTransfer.io.writeRequest.bits.address := lineAddress
    lineTransfer.io.writeRequest.bits.data := lineData.asUInt
    lineTransfer.io.writeRequest.bits.tag := 0.U
    when(lineTransfer.io.writeRequest.fire) { state := lineWriteWait }
    lineTransfer.io.writeResponse.ready := state === lineWriteWait
    when(lineTransfer.io.writeResponse.fire) {
        assert(!lineTransfer.io.writeResponse.bits.error,
            "coherent home backing RAM rejected a dirty line writeback")
        when(releaseOrigin) {
            owned(lineIndex(lineAddress)) := false.B
            state := releaseAck
        }.elsewhen(probeForAcquire) {
            // ProbeAckData already supplied the full line. Backing RAM is now current;
            // forwarding the buffered data avoids a redundant eight-beat refill.
            beat := 0.U
            state := grant
        }.otherwise { state := accessSend }
    }
    when(state === releaseAck && client(releaseClient).d.fire) { state := resume }
}
