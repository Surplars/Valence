package ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLParams, TLOpcode}
import soc.ip.tilelink.TwoMasterTileLinkArbiter
import soc.core.ooo._

/** Adapted from PostedStoreHomeGsim: identical real home/AXI transport, with
  * posted merge always ON and only CPU return tagging varied. Four legal posted
  * owner allocations exhaust the two-bit lifetime counter without state pokes.
  * The host supplies checked committed-physical proofs as boundary premises.
  * This does not qualify ROB authority or an executing FP instruction pipeline.
  */
class TaggedPostedReturnHomeGsim(tagged: Boolean) extends Module {
    private val enabled = true
    private val generationBits = 2
    private val wbEntries = 2
    private val returns = if (tagged) Some(CpuReturnConfig(4, 2, fpEnabled = true)) else None
    private val returnBits = returns.map(_.handleBits).getOrElse(0)
    private val concurrency = CoherentCacheConcurrency(2, 2, wbEntries,
        overlapWritebackRefill = wbEntries > 1, independentDemandAdmission = true)
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3,
        sinkBits = concurrency.sinkBits)
    private val c = PostedStoreMergeConfig(enabled = true, tokenTagBits = 64, tokenIndexBits = 4,
        generationBits = generationBits, cacheSets = 8, cacheWays = 2, writebackEntries = wbEntries,
        guaranteedBase = 4096, guaranteedBytes = 4096)
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort(returnBits))
        val taggedEnabled = Output(Bool())
        val configuredGenerationBits = Output(UInt(7.W))
        val dma = Flipped(new DataPort)
        val ddrAxi = new soc.ip.axi.Axi4MemoryPort(32, 4)
        val holdAcquire = Input(Bool())
        val holdGrantAck = Input(Bool())
        val holdReleaseAck = Input(Bool())
        val holdCoherentC = Input(Bool())
        val monAValid = Output(UInt(64.W))
        val monAReady = Output(UInt(64.W))
        val monCValid = Output(UInt(64.W))
        val monCReady = Output(UInt(64.W))
        val monCOpcode = Output(UInt(64.W))
        val monCSource = Output(UInt(64.W))
        val monDValid = Output(UInt(64.W))
        val monDReady = Output(UInt(64.W))
        val monDOpcode = Output(UInt(64.W))
        val monDSource = Output(UInt(64.W))
        val posted = new PostedStoreCachePort(c)
        val flushRequest = Input(Bool())
        val flushDone = Output(Bool())
        val hit = Output(Bool())
        val accepted = Output(Valid(new PostedStoreAcceptance(c)))
        val acknowledged = Output(Valid(new PostedStoreMember(c)))
        val released = Output(Valid(new PostedLineEvent(c)))
        val fallback = Output(Valid(new PostedFallbackAcknowledgement(c)))
        val fallbackAck = Output(Valid(new PostedFallbackAcknowledgement(c)))
        val failed = Output(Bool())
        val lineWrite = Output(Bool())
        val lineWritePosted = Output(Bool())
        val lineWriteAddress = Output(UInt(64.W))
        val installWord0 = Output(UInt(64.W)); val installWord1 = Output(UInt(64.W))
        val installWord2 = Output(UInt(64.W)); val installWord3 = Output(UInt(64.W))
        val installWord4 = Output(UInt(64.W)); val installWord5 = Output(UInt(64.W))
        val installWord6 = Output(UInt(64.W)); val installWord7 = Output(UInt(64.W))
    })
    val cache = Module(new NonBlockingCoherentLineCache(base = 4096, bytes = 4096, lines = 16,
        params = params, ways = 2, concurrency = concurrency,
        tagConfig = CacheTagConfig(compact = true, bankedStorage = true),
        postedConfig = Some(c), returnConfig = returns))
    io.upstream <> cache.io.upstream
    io.taggedEnabled := tagged.B
    io.configuredGenerationBits := generationBits.U
    val memory = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val home = Module(new MixedCoherentLineHome(params, base = 4096, bytes = 4096,
        trackedLines = 16, trackedWays = 2, acquireEntries = 2,
        tagConfig = CacheTagConfig(compact = true, bankedStorage = true),
        writebackEntries = wbEntries, mixedReadWrite = wbEntries > 1))
    val atomic = Module(new AtomicDataMemory(4096, 4096, registerResponseOwners = true))
    val requests = Module(new DataRequestBuffer(registerHead = true))
    val ordered = Module(new OrderedTileLinkBridge(allowWriteErrors = true, allowPartialWrites = true))
    val arbiter = Module(new TwoMasterTileLinkArbiter(memory))
    val ddr = Module(new TileLinkAxi4Bridge(tlParams = memory.copy(sourceBits = 4),
        axiAddressWidth = 32, axiIdWidth = 4, maxOutstanding = 4, maxBurstBeats = 8,
        maxOutstandingWrites = (if (wbEntries > 1) wbEntries else 0),
        unorderedResponses = true, axiAddressBase = 4096, axiWindowBytes = 4096))
    atomic.io.cpu <> cache.io.downstream
    atomic.io.dma <> io.dma
    atomic.io.clearReservation := false.B
    requests.io.upstream <> atomic.io.memory
    requests.io.requestCpu := atomic.io.memoryRequestCpu
    home.io.upstream <> requests.io.downstream
    home.io.upstreamRequestCpu := requests.io.downstreamRequestCpu
    home.io.clients(0) <> cache.io.tl
    home.io.clients(0).a.valid := cache.io.tl.a.valid && !io.holdAcquire
    cache.io.tl.a.ready := home.io.clients(0).a.ready && !io.holdAcquire
    home.io.clients(0).c.valid := cache.io.tl.c.valid && !io.holdCoherentC
    cache.io.tl.c.ready := home.io.clients(0).c.ready && !io.holdCoherentC
    home.io.clients(0).e.valid := cache.io.tl.e.valid && !io.holdGrantAck
    cache.io.tl.e.ready := home.io.clients(0).e.ready && !io.holdGrantAck
    // A test-only transport queue retains real home-produced ReleaseAck messages.
    // No fake source, permission, data or completion is synthesized here.
    val delayedAcks = Module(new Queue(chiselTypeOf(home.io.clients(0).d.bits), 4))
    val homeD = home.io.clients(0).d
    val incomingAck = homeD.bits.opcode === TLOpcode.ReleaseAck
    val captureAck = incomingAck && (io.holdReleaseAck || delayedAcks.io.deq.valid)
    val replayAck = delayedAcks.io.deq.valid && !io.holdReleaseAck && (!homeD.valid || incomingAck)
    delayedAcks.io.enq.valid := homeD.valid && captureAck
    delayedAcks.io.enq.bits := homeD.bits
    delayedAcks.io.deq.ready := replayAck && cache.io.tl.d.ready
    cache.io.tl.d.valid := replayAck || (homeD.valid && !captureAck)
    cache.io.tl.d.bits := Mux(replayAck, delayedAcks.io.deq.bits, homeD.bits)
    homeD.ready := Mux(captureAck, delayedAcks.io.enq.ready, !replayAck && cache.io.tl.d.ready)
    ordered.io.data <> home.io.downstream
    arbiter.io.masters(0) <> ordered.io.tl
    CoherentHomeUlBoundary.connect(home.io.line, arbiter.io.masters(1))
    ddr.io.tl <> arbiter.io.manager
    io.ddrAxi <> ddr.io.axi
    home.io.drainRequest := io.flushRequest && cache.io.flushDone
    io.monAValid := cache.io.tl.a.valid
    io.monAReady := cache.io.tl.a.ready
    io.monCValid := cache.io.tl.c.valid
    io.monCReady := cache.io.tl.c.ready
    io.monCOpcode := cache.io.tl.c.bits.opcode
    io.monCSource := cache.io.tl.c.bits.source
    io.monDValid := cache.io.tl.d.valid
    io.monDReady := cache.io.tl.d.ready
    io.monDOpcode := cache.io.tl.d.bits.opcode
    io.monDSource := cache.io.tl.d.bits.source
    cache.io.flushRequest := io.flushRequest
    io.flushDone := cache.io.flushDone && home.io.drainDone
    io.hit := cache.io.hit
    if (enabled) io.posted <> cache.io.posted.get
    else { io.posted.busy := false.B; io.posted.episodeActive := false.B }
    val observation = if (enabled) BoringUtils.bore(cache.observationPosted.get)
        else 0.U.asTypeOf(new PostedStoreCacheObservation(c))
    val line = BoringUtils.bore(cache.observationLineWrite)
    io.accepted := observation.accepted
    io.acknowledged := observation.acknowledged
    io.released := observation.released
    io.fallback := observation.fallback
    io.fallbackAck := observation.fallbackAck
    io.failed := observation.failed
    io.lineWrite := line.valid
    io.lineWritePosted := line.posted
    io.lineWriteAddress := line.address
    Seq(io.installWord0, io.installWord1, io.installWord2, io.installWord3,
        io.installWord4, io.installWord5, io.installWord6, io.installWord7).zipWithIndex.foreach {
        case (port, i) => port := line.data(64 * i + 63, 64 * i)
    }
}

object TaggedPostedReturnHomeGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)), "output directory and tagged 0|1 required")
    ChiselStage.emitCHIRRTLFile(new TaggedPostedReturnHomeGsim(args(1) == "1"), Array("--target-dir", args.head))
}
