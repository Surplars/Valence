package ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.ip.ethernet.{EthernetDmaFrameAdapter, GmiiFrameRx}
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundle, TLParams, TLOpcode}
import soc.core.ooo._
import soc.ip.bus.{RegisterArbiter, RegisterPort}
import soc.ip.dma.{EthernetAxisWord, EthernetPacketDma, MemoryCopyDma}
import soc.ip.tilelink.TwoMasterTileLinkArbiter

/** Selected combined-timing-repair memory profile with real common-clock GMII MAC and packet DMA.
  * No CPU core, Linux, CDC, or board timing qualification. Copy DMA is provably idle.
  */
class EthernetHomeRxGsim(macPrefetch: Boolean, dmaPrefetch: Boolean) extends Module {
    private val lineTransfers = true
    private val lineYieldCycles = 0
    private val lineEntries = 4
    private val base = BigInt("80200000", 16)
    private val bytes = BigInt(2) * 1024 * 1024 * 1024
    private val tags = CacheTagConfig(compact = true, bankedStorage = true)
    private val cfg = CoherentCacheConcurrency(
        concurrentReadStorePrefetch = true,
        distinctWayRelease = false,
        durableReadPrefetchCandidate = true,
        futureHomeWayReservation = true,
        independentDemandAdmission = true,
        internalLineGrant = true,
        memoryScheduleOverlap = true,
        nextLinePrefetch = true,
        overlapWritebackRefill = true,
        postedPrefetchCoexistence = true,
        prefetchBreakOnStore = false,
        prefetchCandidateCycles = 16,
        readMshrs = 2,
        readPrefetchBehindStore = true,
        readPrefetchDemandAdoption = true,
        readPrefetchDirtyRetry = true,
        readPrefetchStoreHold = true,
        responseEntries = 2,
        splitPrefetchTracking = true,
        storeNextLinePrefetch = true,
        storePrefetchLruVictim = true,
        storePrefetchMruInsertion = true,
        writebackEntries = 2)
    private val posted = Some(PostedStoreMergeConfig(enabled = true, guaranteedBase = base, guaranteedBytes = bytes))
    private val returns = Some(CpuReturnConfig(4, 2, true))
    private val coherent = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 1)
    private val memory = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val control = Flipped(new RegisterPort)
        val gmiiData = Input(UInt(8.W))
        val gmiiValid = Input(Bool())
        val gmiiError = Input(Bool())
        val accepted = Output(Bool())
        val dropped = Output(Bool())
        val dataFire = Output(Bool())
        val dataWord = Output(UInt(32.W))
        val dataKeep = Output(UInt(4.W))
        val statusWord = Output(UInt(32.W))
        val statusKeep = Output(UInt(4.W))
        val dmaState = Output(UInt(3.W))
        val macPending = Output(Bool())
        val dmaPending = Output(Bool())
        val bankRelease = Output(Bool())
        val dataLast = Output(Bool())
        val statusFire = Output(Bool())
        val statusLast = Output(Bool())
        val collectDone = Output(Bool())
        val completion = Output(Bool())
        val failed = Output(Bool())
        val activeAddress = Output(UInt(64.W))
        val activeBytes = Output(UInt(17.W))
        val owned = Output(UInt(3.W))
        val completed = Output(UInt(3.W))
        val pending = Output(UInt(3.W))
        val outstanding = Output(UInt(10.W))
        val macOccupied = Output(UInt(3.W))
        val macPrefetchOccupied = Output(UInt(2.W))
        val dmaPrefetchOccupied = Output(UInt(3.W))
        val creditStall = Output(Bool())
        val storeEmpty = Output(Bool())
        val stageRequestOffer = Output(UInt(8.W))
        val stageRequestReady = Output(UInt(8.W))
        val stageRequestFire = Output(UInt(8.W))
        val stageResponseOffer = Output(UInt(8.W))
        val stageResponseReady = Output(UInt(8.W))
        val stageResponseFire = Output(UInt(8.W))
        val debugArbiterOwners = Output(UInt(4.W))
        val systemArbiterOwners = Output(UInt(4.W))
        val lineReadFire = Output(Bool())
        val lineReadResponseFire = Output(Bool())
        val arbiterOwners = Output(UInt(4.W))
        val adapterOwners = Output(UInt(4.W))
        val atomicOwners = Output(UInt(4.W))
        val bufferOccupied = Output(UInt(2.W))
        val orderedOwners = Output(UInt(4.W))
        val copyRequestOffer = Output(Bool())
        val memoryAOffer = Output(Bool())
        val memoryAFire = Output(Bool())
        val memoryASource = Output(UInt(5.W))
        val memoryAAddress = Output(UInt(64.W))
        val memoryAOpcode = Output(UInt(3.W))
        val memoryDFire = Output(Bool())
        val memoryDSource = Output(UInt(5.W))
        val packetActive = Output(Bool())
        val packetIrq = Output(Bool())
        val packetRequestFire = Output(Bool())
        val packetRequestOffer = Output(Bool())
        val packetRequestReady = Output(Bool())
        val packetRequestWrite = Output(Bool())
        val packetRequestAddress = Output(UInt(64.W))
        val packetRequestData = Output(UInt(64.W))
        val packetRequestMask = Output(UInt(8.W))
        val packetRequestSize = Output(UInt(2.W))
        val packetResponseFire = Output(Bool())
        val packetResponseError = Output(Bool())
        val cpu = Flipped(new DataPort(returns.get.handleBits))
        val ddrAxi = new soc.ip.axi.Axi4MemoryPort(32, 4)
        val active = Output(Bool())
        val atomicActive = Output(Bool())
        val irq = Output(Bool())
        val flushRequest = Input(Bool())
        val holdLineHome = Input(Bool())
        val lineRequestOffer = Output(Bool())
        val flushDone = Output(Bool())
        val hit = Output(Bool())
        val miss = Output(Bool())
        val probeFire = Output(Bool())
        val probeReplyFire = Output(Bool())
        val probeReplyData = Output(Bool())
        val dmaRequestFire = Output(Bool())
        val dmaRequestWrite = Output(Bool())
        val dmaRequestAddress = Output(UInt(64.W))
        val dmaRequestData = Output(UInt(64.W))
        val dmaResponseFire = Output(Bool())
        val dmaResponseError = Output(Bool())
        val lineRequestFire = Output(Bool())
        val lineRequestWrite = Output(Bool())
        val lineRequestAddress = Output(UInt(64.W))
        val lineResponseFire = Output(Bool())
        val lineResponseError = Output(Bool())
        val homeRequestOffer = Output(Bool())
        val homeRequestFire = Output(Bool())
        val homeResponseFire = Output(Bool())
    })
    val dma = Module(new MemoryCopyDma(ramBase = base, ramBytes = bytes, lineTransfers = lineTransfers, lineYieldCycles = lineYieldCycles, lineEntries = lineEntries))
    val packet = Module(new EthernetPacketDma(ramBase = base, ramBytes = bytes, postedRxSlots = 4,
        memoryCredits = 4, postedTxSlots = 4, maxFrameBytes = 2048, rxWritePrefetch = dmaPrefetch))
    val scalarArbiter = Module(new RegisterArbiter)
    val debugArbiter = Module(new RegisterArbiter)
    val systemArbiter = Module(new SharedDataArbiter(registerResponseOwners = true))
    val adapter = Module(new DmaRegisterDataAdapter)
    val cache = CoherentLineCacheModule.build(base, bytes, 512, coherent, 2, cfg, tags,
        postedConfig = posted, returnConfig = returns, registerProbeLookup = true, localReadSelection = true,
        allowSharedFutureLruWriteData = true, disjointEvictionStoreOverlap = true)
    cache.io.posted.get.requestProof := 0.U.asTypeOf(cache.io.posted.get.requestProof)
    cache.io.posted.get.contextEpoch := 0.U
    cache.io.posted.get.seal := false.B
    cache.io.posted.get.endEpisode := !io.cpu.request.valid && !cache.io.posted.get.busy
    val home = CoherentLineHomeModule.build(params = coherent, base = base, bytes = bytes, trackedLines = 512,
        trackedWays = 2, acquireEntries = 2, tagConfig = tags, writebackEntries = 2, mixedReadWrite = true,
        dmaLineTransfers = lineTransfers, dmaLineEntries = lineEntries, rawResponseMetadata = true,
        parallelQualification = true, distinctWayRelease = false, lineTransferDispatchFlow = true,
        lineReadChannel = true, internalLineGrant = true, memoryScheduleOverlap = true,
        futureHomeWayReservation = true, allowSharedFutureLookup = true)
    val atomic = Module(new AtomicDataMemory(base, bytes, registerResponseOwners = true, dmaLineTransfers = lineTransfers, dmaLineEntries = lineEntries))
    val requests = Module(new DataRequestBuffer(registerHead = true))
    val ordered = Module(new OrderedTileLinkBridge(orderedWrites = true, orderedMixedAccesses = true,
        orderedWriteBankBase = base, orderedWriteBankBytes = 0, allowWriteErrors = true,
        flowHeadResponse = false, allowPartialWrites = true))
    val arbiter = Module(new TwoMasterTileLinkArbiter(memory, rawResponseMetadata = true, rawRequestMetadata = true))
    val ddr = Module(new TileLinkAxi4Bridge(tlParams = memory.copy(sourceBits = 5), axiAddressWidth = 32,
        axiIdWidth = 4, maxOutstanding = 4, maxOutstandingWrites = 2, maxBurstBeats = 16,
        unorderedResponses = true, axiAddressBase = base, axiWindowBytes = bytes,
        writeCollectionFlow = true, lineReadChannel = true, localPayloadWriteEnable = true,
        localPayloadWriteRow = true, localAddressRanges = true))
    dma.io.control.request.valid := false.B
    dma.io.control.request.bits := 0.U.asTypeOf(dma.io.control.request.bits)
    dma.io.control.response.ready := true.B
    packet.io.control <> io.control
    packet.io.txData.ready := true.B
    packet.io.txControl.ready := true.B
    val mac = Module(new GmiiFrameRx(readPrefetch = macPrefetch))
    val frameAdapter = Module(new EthernetDmaFrameAdapter)
    mac.io.gmiiData := io.gmiiData
    mac.io.gmiiValid := io.gmiiValid
    mac.io.gmiiError := io.gmiiError
    mac.io.enable := true.B
    mac.io.promiscuous := false.B
    mac.io.broadcastEnable := true.B
    mac.io.macAddress := "h021122334455".U
    frameAdapter.io.rxFrame <> mac.io.frame
    packet.io.rxData <> frameAdapter.io.rxData
    packet.io.rxStatus <> frameAdapter.io.rxStatus
    frameAdapter.io.txData.valid := false.B
    frameAdapter.io.txData.bits := 0.U.asTypeOf(frameAdapter.io.txData.bits)
    frameAdapter.io.txControl.valid := false.B
    frameAdapter.io.txControl.bits := 0.U.asTypeOf(frameAdapter.io.txControl.bits)
    frameAdapter.io.txFrame.ready := true.B
    io.accepted := mac.io.accepted
    io.dropped := mac.io.dropped
    io.macOccupied := BoringUtils.bore(mac.occupied)
    io.macPending := BoringUtils.bore(mac.readPrefetchPending)
    io.macPrefetchOccupied := BoringUtils.bore(mac.readPrefetchOccupancy)
    io.bankRelease := mac.io.frame.fire && mac.io.frame.bits.last
    io.dataWord := packet.io.rxData.bits.data
    io.dataKeep := packet.io.rxData.bits.keep
    io.statusWord := packet.io.rxStatus.bits.data
    io.statusKeep := packet.io.rxStatus.bits.keep
    io.dmaState := BoringUtils.bore(packet.rxState)
    io.dmaPending := BoringUtils.bore(packet.rxPrefetchPending)
    io.dataFire := packet.io.rxData.fire
    io.dataLast := packet.io.rxData.bits.last
    io.statusFire := packet.io.rxStatus.fire
    io.statusLast := packet.io.rxStatus.bits.last
    io.collectDone := BoringUtils.bore(packet.rxDataDone) && BoringUtils.bore(packet.rxStatusDone)
    io.completion := BoringUtils.bore(packet.complete)
    io.failed := BoringUtils.bore(packet.rxFailed)
    io.activeAddress := BoringUtils.bore(packet.rxAddress)
    io.activeBytes := BoringUtils.bore(packet.rxBytes)
    io.owned := BoringUtils.bore(packet.ownedCount)
    io.completed := BoringUtils.bore(packet.completedCount)
    io.pending := BoringUtils.bore(packet.pendingCount)
    io.outstanding := BoringUtils.bore(packet.rxIssued) - BoringUtils.bore(packet.rxReplied)
    io.dmaPrefetchOccupied := BoringUtils.bore(packet.rxPrefetchOccupancy)
    io.creditStall := BoringUtils.bore(packet.rxState) === 4.U && io.outstanding === 4.U
    io.storeEmpty := BoringUtils.bore(packet.rxState) === 4.U && !packet.io.memory.request.valid && io.outstanding < 4.U
    io.copyRequestOffer := dma.io.memory.request.valid
    assert(!dma.io.memory.request.valid, "idle copy DMA offered scalar request")
    assert(!dma.io.line.get.request.valid, "idle copy DMA offered line request")
    assert(!dma.io.active, "idle copy DMA became active")
    scalarArbiter.io.clients(0) <> dma.io.memory
    scalarArbiter.io.clients(1) <> packet.io.memory
    debugArbiter.io.clients(0) <> scalarArbiter.io.memory
    debugArbiter.io.clients(1).request.valid := false.B
    debugArbiter.io.clients(1).request.bits := 0.U.asTypeOf(debugArbiter.io.clients(1).request.bits)
    debugArbiter.io.clients(1).response.ready := true.B
    adapter.io.registers <> debugArbiter.io.memory
    assert(!debugArbiter.io.clients(1).request.valid, "idle debug source became active")
    io.packetActive := packet.io.active
    io.packetIrq := packet.io.irq
    io.packetRequestFire := packet.io.memory.request.fire
    io.packetRequestOffer := packet.io.memory.request.valid
    io.packetRequestReady := packet.io.memory.request.ready
    io.packetRequestWrite := packet.io.memory.request.bits.write
    io.packetRequestAddress := packet.io.memory.request.bits.address
    io.packetRequestData := packet.io.memory.request.bits.data
    io.packetRequestMask := packet.io.memory.request.bits.byteEnable
    io.packetRequestSize := packet.io.memory.request.bits.size
    io.packetResponseFire := packet.io.memory.response.fire
    io.packetResponseError := packet.io.memory.response.bits.error
    if (lineTransfers) {
        atomic.io.dmaLine.get <> dma.io.line.get
        home.io.dmaLine.get <> atomic.io.memoryLine.get
    }
    cache.io.upstream <> io.cpu
    cache.io.upstream.request.bits.prefetchNextAllowed := false.B
    cache.io.flushRequest := io.flushRequest
    home.io.drainRequest := (io.flushRequest && cache.io.flushDone) || io.holdLineHome
    io.flushDone := cache.io.flushDone && home.io.drainDone
    atomic.io.cpu <> cache.io.downstream
    atomic.io.dma <> adapter.io.data
    atomic.io.clearReservation := false.B
    systemArbiter.io.clients(0) <> atomic.io.memory
    systemArbiter.io.clients(1).request.valid := false.B
    systemArbiter.io.clients(1).request.bits := 0.U.asTypeOf(systemArbiter.io.clients(1).request.bits)
    systemArbiter.io.clients(1).response.ready := true.B
    requests.io.upstream <> systemArbiter.io.memory
    requests.io.requestCpu := systemArbiter.io.memoryRequestClient0 && atomic.io.memoryRequestCpu
    assert(!systemArbiter.io.clients(1).request.valid, "idle walker source became active")
    home.io.upstream <> requests.io.downstream
    home.io.upstreamRequestCpu := requests.io.downstreamRequestCpu
    home.io.clients(0) <> cache.io.tl
    cache.io.lineGrant.get <> home.io.lineGrants.get(0)
    ordered.io.data <> home.io.downstream
    arbiter.io.masters(0) <> ordered.io.tl
    CoherentHomeUlBoundary.connect(home.io.line, arbiter.io.masters(1), registerRequests = true)
    val boundary = Module(new soc.ip.tilelink.RegisteredTileLinkBoundary(memory.copy(sourceBits = 4)))
    val fetchBoundary = Module(new soc.ip.tilelink.RegisteredTileLinkBoundary(memory.copy(sourceBits = 4)))
    val crossbar = Module(new soc.ip.tilelink.TwoMasterTwoBankTileLinkCrossbar(memory.copy(sourceBits = 4),
        base = BigInt("80000000", 16), bankBytes = BigInt("200000", 16), secondBankBytes = bytes,
        prefixAddressDecode = true, rawResponseMetadata = true, rawRequestMetadata = true))
    boundary.io.upstream <> arbiter.io.manager
    crossbar.io.masters(0) <> boundary.io.downstream
    fetchBoundary.io.upstream.a.valid := false.B
    fetchBoundary.io.upstream.a.bits := 0.U.asTypeOf(fetchBoundary.io.upstream.a.bits)
    fetchBoundary.io.upstream.d.ready := true.B
    TLBundle.tieoffMasterCoherence(fetchBoundary.io.upstream)
    crossbar.io.masters(1) <> fetchBoundary.io.downstream
    crossbar.io.banks(0).a.ready := false.B
    crossbar.io.banks(0).d.valid := false.B
    crossbar.io.banks(0).d.bits := 0.U.asTypeOf(crossbar.io.banks(0).d.bits)
    TLBundle.tieoffSlaveCoherence(crossbar.io.banks(0))
    assert(!crossbar.io.masters(1).a.valid, "idle instruction source became active")
    assert(!crossbar.io.banks(0).a.valid, "standalone Ethernet touched omitted ROM")
    ddr.io.tl <> crossbar.io.banks(1)
    ddr.io.lineRead.get <> home.io.lineRead.get
    io.lineReadFire := ddr.io.lineRead.get.request.fire
    io.lineReadResponseFire := ddr.io.lineRead.get.response.fire
    io.ddrAxi <> ddr.io.axi
    // Stage0 packet;1 scalar arbiter;2 debug arbiter;3 adapter;4 atomic;
    // 5 system arbiter/buffer in;6 buffer out/home in;7 home out/ordered in.
    val observedRequests = Seq(packet.io.memory.request, scalarArbiter.io.memory.request,
        debugArbiter.io.memory.request, adapter.io.data.request, atomic.io.memory.request,
        systemArbiter.io.memory.request, requests.io.downstream.request, home.io.downstream.request)
    val observedResponses = Seq(packet.io.memory.response, scalarArbiter.io.memory.response,
        debugArbiter.io.memory.response, adapter.io.data.response, atomic.io.memory.response,
        systemArbiter.io.memory.response, requests.io.downstream.response, home.io.downstream.response)
    io.stageRequestOffer := VecInit(observedRequests.map(_.valid)).asUInt
    io.stageRequestReady := VecInit(observedRequests.map(_.ready)).asUInt
    io.stageRequestFire := VecInit(observedRequests.map(_.fire)).asUInt
    io.stageResponseOffer := VecInit(observedResponses.map(_.valid)).asUInt
    io.stageResponseReady := VecInit(observedResponses.map(_.ready)).asUInt
    io.stageResponseFire := VecInit(observedResponses.map(_.fire)).asUInt
    io.debugArbiterOwners := BoringUtils.bore(debugArbiter.owners.io.count)
    io.systemArbiterOwners := BoringUtils.bore(systemArbiter.owners.io.count)
    io.arbiterOwners := BoringUtils.bore(scalarArbiter.owners.io.count)
    io.adapterOwners := BoringUtils.bore(adapter.lanes.io.count)
    io.atomicOwners := BoringUtils.bore(atomic.unit.owners.io.count)
    io.bufferOccupied := BoringUtils.bore(requests.requests.count)
    io.orderedOwners := BoringUtils.bore(ordered.order.io.count)
    io.memoryAOffer := ddr.io.tl.a.valid
    io.memoryAFire := ddr.io.tl.a.fire
    io.memoryASource := ddr.io.tl.a.bits.source
    io.memoryAAddress := ddr.io.tl.a.bits.address
    io.memoryAOpcode := ddr.io.tl.a.bits.opcode
    io.memoryDFire := ddr.io.tl.d.fire
    io.memoryDSource := ddr.io.tl.d.bits.source
    val atomicActive = RegInit(false.B)
    when(atomic.io.cpu.request.fire && atomic.io.cpu.request.bits.atomic && atomic.io.cpu.request.bits.atomicOp === 0.U) { atomicActive := true.B }
    when(atomic.io.cpu.response.fire) { atomicActive := false.B }
    io.atomicActive := atomicActive
    io.active := dma.io.active
    io.irq := dma.io.irq
    io.hit := cache.io.hit
    io.miss := cache.io.miss
    io.probeFire := cache.io.tl.b.fire
    io.probeReplyFire := cache.io.tl.c.fire && !TLOpcode.isRelease(cache.io.tl.c.bits.opcode)
    io.probeReplyData := cache.io.tl.c.bits.opcode === TLOpcode.ProbeAckData
    io.dmaRequestFire := dma.io.memory.request.fire
    io.dmaRequestWrite := dma.io.memory.request.bits.write
    io.dmaRequestAddress := dma.io.memory.request.bits.address
    io.dmaRequestData := dma.io.memory.request.bits.data
    io.dmaResponseFire := dma.io.memory.response.fire
    io.dmaResponseError := dma.io.memory.response.bits.error
    io.lineRequestOffer := (if (lineTransfers) dma.io.line.get.request.valid else false.B)
    io.lineRequestFire := (if (lineTransfers) dma.io.line.get.request.fire else false.B)
    io.lineRequestWrite := (if (lineTransfers) dma.io.line.get.request.bits.write else false.B)
    io.lineRequestAddress := (if (lineTransfers) dma.io.line.get.request.bits.address else 0.U)
    io.lineResponseFire := (if (lineTransfers) dma.io.line.get.response.fire else false.B)
    io.lineResponseError := (if (lineTransfers) dma.io.line.get.response.bits.error else false.B)
    io.homeRequestOffer := home.io.upstream.request.valid
    io.homeRequestFire := home.io.upstream.request.fire
    io.homeResponseFire := home.io.upstream.response.fire
}

object EthernetHomeRxGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new EthernetHomeRxGsim(args(1) == "1", args(2) == "1"),
        Array("--target-dir", args(0)))
}
