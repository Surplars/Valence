package ooo

import chisel3._
import chisel3.util.log2Ceil
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLParams, TLOpcode}
import soc.core.ooo._
import soc.ip.tilelink.TwoMasterTileLinkArbiter

/** Real cache, coherent home, atomic/DMA ownership boundary and AXI bridge.
  * Only backing memory and CPU/DMA request expectations are independent C++.
  * This is not a CPU/board model and has no synthetic coherence responder.
  */
class CoherentCacheHomeGsim(mshrs: Int = 2, lines: Int = 512, responseEntries: Int = 2, compactTags: Boolean = false, writebacks: Int = 1, mixed: Boolean = false, axiSlots: Int = 4, unordered: Boolean = false, prefetch: Boolean = false, bankedTags: Boolean = false, prefetchCandidateCycles: Int = 1,
    testBase: BigInt = BigInt("80010000", 16), prefetchBreakOnStore: Boolean = false,
    storeNextLinePrefetch: Boolean = false, observeStorePrefetch: Boolean = false,
    storePrefetchMruInsertion: Boolean = false) extends Module {
    private val base = testBase
    private val bytes = BigInt(128 * 1024)
    private val cfg = CoherentCacheConcurrency(mshrs, responseEntries, writebacks, mixed, nextLinePrefetch = prefetch,
        prefetchCandidateCycles = prefetchCandidateCycles, prefetchBreakOnStore = prefetchBreakOnStore,
        storeNextLinePrefetch = storeNextLinePrefetch, storePrefetchMruInsertion = storePrefetchMruInsertion)
    private val coherent = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = cfg.sinkBits)
    private val memory = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val storePfObs = if (observeStorePrefetch) Some(Output(new CheckedStorePrefetchObservation(log2Ceil(mshrs)))) else None
        val prefetchPmpCfg = Input(UInt(8.W))
        val prefetchPmpAddress = Input(UInt(54.W))
        val prefetchPrivilege = Input(UInt(2.W))
        val bypassPrefetchAuthorization = Input(Bool()) // negative-control fixture only
        val prefetchBusy = Output(Bool())
        val prefetchEvents = Output(new DataPrefetchEvents)
        val cpu = Flipped(new DataPort)
        val dma = Flipped(new DataPort)
        val ddrAxi = new soc.ip.axi.Axi4MemoryPort(32, 4)
        val flushRequest = Input(Bool())
        val flushDone = Output(Bool())
        val cacheFlushDone = Output(Bool())
        val homeDrainDone = Output(Bool())
        val hit = Output(Bool())
        val miss = Output(Bool())
        val dirtyEviction = Output(Bool())
        val acquireFire = Output(Bool())
        val acquireOffer = Output(Bool())
        val acquireSource = Output(UInt(3.W))
        val acquireAddress = Output(UInt(64.W))
        val grantFire = Output(Bool())
        val grantSource = Output(UInt(3.W))
        val grantSink = Output(UInt(2.W))
        val grantAckFire = Output(Bool())
        val grantAckOffer = Output(Bool())
        val grantAckSink = Output(UInt(2.W))
        val releaseFire = Output(Bool())
        val releaseData = Output(Bool())
        val releaseAddress = Output(UInt(64.W))
        val releaseAckFire = Output(Bool())
        val releaseSource = Output(UInt(3.W))
        val releaseAckSource = Output(UInt(3.W))
        val holdGrantAck = Input(Bool())
        val holdCoherentD = Input(Bool())
        val holdReleaseAck = Input(Bool())
        val holdCoherentC = Input(Bool())
        val probeOffer = Output(Bool())
        val probeFire = Output(Bool())
        val probeAddress = Output(UInt(64.W))
        val probeReplyFire = Output(Bool())
        val probeReplyData = Output(Bool())
    })
    val tags = CacheTagConfig(compact = compactTags, bankedStorage = bankedTags)
    val cache = CoherentLineCacheModule.build(base, bytes, lines, coherent, 2, cfg, tags)
    io.storePfObs.foreach { out =>
        require(mshrs >= 2, "store PF observer requires nonblocking cache")
        out := BoringUtils.bore(cache.asInstanceOf[NonBlockingCoherentLineCache].observationStorePrefetch)
    }
    val home = CoherentLineHomeModule.build(coherent, base, bytes, trackedLines = lines,
        trackedWays = 2, acquireEntries = mshrs, tagConfig = tags, writebackEntries = writebacks, mixedReadWrite = mixed)
    val atomic = Module(new AtomicDataMemory(base, bytes, registerResponseOwners = true))
    val requests = Module(new DataRequestBuffer(registerHead = true))
    val ordered = Module(new OrderedTileLinkBridge(allowWriteErrors = true, allowPartialWrites = true))
    val arbiter = Module(new TwoMasterTileLinkArbiter(memory))
    val ddr = Module(new TileLinkAxi4Bridge(tlParams = memory.copy(sourceBits = 4),
        axiAddressWidth = 32, axiIdWidth = 4, maxOutstanding = axiSlots, maxBurstBeats = 8, maxOutstandingWrites = (if (mixed) writebacks else 0), unorderedResponses = unordered,
        axiAddressBase = base, axiWindowBytes = bytes))
    io.prefetchBusy := cache.io.prefetchBusy
    io.prefetchEvents := cache.io.prefetch
    cache.io.upstream <> io.cpu
    if (prefetch) {
        val p = OooParams(machineSystem = true, pmpEntries = 16, virtualMemoryLevels = 3,
            speculativeRamBase = base, speculativeRamBytes = bytes,
            dataNextLinePrefetch = true, dataStoreNextLinePrefetch = storeNextLinePrefetch)
        val auth = Module(new NextLineAuthorization(p))
        val state = WireDefault(0.U.asTypeOf(new PmpState))
        state.cfg(0) := io.prefetchPmpCfg
        state.addr(0) := io.prefetchPmpAddress
        PmpState.decodeRegions(state)
        auth.io.request := io.cpu.request.bits
        auth.io.privilege := io.prefetchPrivilege
        auth.io.pmpState := state
        auth.io.fault := false.B
        cache.io.upstream.request.bits.prefetchNextAllowed := auth.io.allowed || io.bypassPrefetchAuthorization
    } else cache.io.upstream.request.bits.prefetchNextAllowed := false.B
    cache.io.flushRequest := io.flushRequest
    home.io.drainRequest := io.flushRequest && cache.io.flushDone
    io.flushDone := cache.io.flushDone && home.io.drainDone
    io.cacheFlushDone := cache.io.flushDone
    io.homeDrainDone := home.io.drainDone
    when(io.flushRequest && cache.io.flushDone) {
        assert(!cache.io.tl.a.valid, "cache-local flush retained Acquire")
    }
    io.hit := cache.io.hit
    io.miss := cache.io.miss
    io.dirtyEviction := cache.io.profile.dirtyEviction
    atomic.io.cpu <> cache.io.downstream
    atomic.io.dma <> io.dma
    atomic.io.clearReservation := false.B
    requests.io.upstream <> atomic.io.memory
    requests.io.requestCpu := atomic.io.memoryRequestCpu
    home.io.upstream <> requests.io.downstream
    home.io.upstreamRequestCpu := requests.io.downstreamRequestCpu
    home.io.clients(0) <> cache.io.tl
    home.io.clients(0).c.valid := cache.io.tl.c.valid && !io.holdCoherentC
    cache.io.tl.c.ready := home.io.clients(0).c.ready && !io.holdCoherentC
    home.io.clients(0).e.valid := cache.io.tl.e.valid && !io.holdGrantAck
    cache.io.tl.e.ready := home.io.clients(0).e.ready && !io.holdGrantAck
    // Test-only acknowledgement delay: consumed home Ack owners are held while
    // later Grant bursts may pass. Empty/unheld mode is the original direct path.
    val delayedAcks = Module(new chisel3.util.Queue(chiselTypeOf(home.io.clients(0).d.bits), 4))
    val homeD = home.io.clients(0).d
    val incomingAck = homeD.bits.opcode === TLOpcode.ReleaseAck
    val captureAck = incomingAck && (io.holdReleaseAck || delayedAcks.io.deq.valid)
    val replayAck = delayedAcks.io.deq.valid && !io.holdReleaseAck && (!homeD.valid || incomingAck)
    delayedAcks.io.enq.valid := homeD.valid && captureAck && !io.holdCoherentD
    delayedAcks.io.enq.bits := homeD.bits
    delayedAcks.io.deq.ready := replayAck && cache.io.tl.d.ready && !io.holdCoherentD
    cache.io.tl.d.valid := (replayAck || (homeD.valid && !captureAck)) && !io.holdCoherentD
    cache.io.tl.d.bits := Mux(replayAck, delayedAcks.io.deq.bits, homeD.bits)
    homeD.ready := !io.holdCoherentD && Mux(captureAck, delayedAcks.io.enq.ready,
        !replayAck && cache.io.tl.d.ready)
    ordered.io.data <> home.io.downstream
    arbiter.io.masters(0) <> ordered.io.tl
    CoherentHomeUlBoundary.connect(home.io.line, arbiter.io.masters(1))
    ddr.io.tl <> arbiter.io.manager
    io.ddrAxi <> ddr.io.axi

    // Protocol-boundary witnesses only: no BoringUtils or CPU-internal tap.
    io.acquireOffer := cache.io.tl.a.valid
    io.acquireFire := cache.io.tl.a.fire
    io.acquireSource := cache.io.tl.a.bits.source
    io.acquireAddress := cache.io.tl.a.bits.address
    io.grantFire := cache.io.tl.d.fire && cache.io.tl.d.bits.opcode === TLOpcode.GrantData
    io.grantSource := cache.io.tl.d.bits.source
    io.grantSink := cache.io.tl.d.bits.sink
    io.grantAckOffer := cache.io.tl.e.valid
    io.grantAckFire := cache.io.tl.e.fire
    io.grantAckSink := cache.io.tl.e.bits.sink
    io.releaseFire := cache.io.tl.c.fire && TLOpcode.isRelease(cache.io.tl.c.bits.opcode)
    io.releaseData := cache.io.tl.c.bits.opcode === TLOpcode.ReleaseData
    io.releaseAddress := cache.io.tl.c.bits.address
    io.releaseSource := cache.io.tl.c.bits.source
    io.releaseAckSource := cache.io.tl.d.bits.source
    io.releaseAckFire := cache.io.tl.d.fire && cache.io.tl.d.bits.opcode === TLOpcode.ReleaseAck
    io.probeOffer := cache.io.tl.b.valid
    io.probeFire := cache.io.tl.b.fire
    io.probeAddress := cache.io.tl.b.bits.address
    io.probeReplyFire := cache.io.tl.c.fire && !TLOpcode.isRelease(cache.io.tl.c.bits.opcode)
    io.probeReplyData := cache.io.tl.c.bits.opcode === TLOpcode.ProbeAckData
}

object CoherentCacheHomeGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new CoherentCacheHomeGsim(args(1).toInt,
        args.lift(2).map(_.toInt).getOrElse(512), args.lift(3).map(_.toInt).getOrElse(2), args.lift(4).contains("1"),
        args.lift(5).map(_.toInt).getOrElse(1), args.lift(6).contains("1"), args.lift(7).map(_.toInt).getOrElse(4), args.lift(8).contains("1"), args.lift(9).contains("1"), args.contains("--banked-cache-tags"),
        args.find(_.startsWith("--prefetch-candidate-cycles=")).map(_.split("=", 2)(1).toInt).getOrElse(1),
        args.find(_.startsWith("--ram-base=")).map(a => BigInt(a.stripPrefix("--ram-base=")))
            .getOrElse(BigInt("80010000", 16)), args.contains("--prefetch-break-on-store")),
        Array("--target-dir", args.head))
}

/** Reconstructed functional gate only. Merge is absent; the original emitter remains unchanged. */
object CheckedStorePrefetchCacheGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)), "output directory and explicit store PF 0|1 required")
    ChiselStage.emitCHIRRTLFile(new CoherentCacheHomeGsim(mshrs = 2, lines = 512,
        responseEntries = 2, compactTags = true, writebacks = 2, mixed = true,
        axiSlots = 4, unordered = true, prefetch = true, bankedTags = true,
        storeNextLinePrefetch = args(1) == "1", observeStorePrefetch = true),
        Array("--target-dir", args(0)))
}

/** Same real cache/home fixture, checked-store PF always ON; only insertion differs. */
object StorePrefetchInsertionGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)), "output directory and explicit store PF MRU 0|1 required")
    ChiselStage.emitCHIRRTLFile(new CoherentCacheHomeGsim(mshrs = 2, lines = 512,
        responseEntries = 2, compactTags = true, writebacks = 2, mixed = true,
        axiSlots = 4, unordered = true, prefetch = true, bankedTags = true,
        storeNextLinePrefetch = true, observeStorePrefetch = true,
        storePrefetchMruInsertion = args(1) == "1"), Array("--target-dir", args(0)))
}
