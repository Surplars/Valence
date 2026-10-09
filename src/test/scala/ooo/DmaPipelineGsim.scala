package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLParams, TLOpcode}
import soc.core.ooo._
import soc.ip.bus.RegisterPort
import soc.ip.dma.MemoryCopyDma
import soc.ip.tilelink.TwoMasterTileLinkArbiter

/** Source-bound DMA/cache/home/AXI fixture. CPU requests and all memory bytes are checked independently in C++. */
class DmaPipelineGsim(lineTransfers: Boolean = true, lineYieldCycles: Int = 0, lineEntries: Int = 1) extends Module {
    private val base = BigInt("80200000", 16)
    private val bytes = BigInt(2) * 1024 * 1024 * 1024
    private val tags = CacheTagConfig(compact = true, bankedStorage = true)
    private val cfg = CoherentCacheConcurrency(2, 2, 2, overlapWritebackRefill = true)
    private val coherent = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 1)
    private val memory = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        // Fixed at reset by the diagnostic driver: 0 real, 1 bypass atomic,
        // 2 DMA -> ideal line slave, 3 DMA -> atomic -> ideal line slave.
        // Bypass modes are component diagnostics, never coherence qualification.
        val diagnosticMode = Input(UInt(2.W))
        val oracle = new soc.ip.dma.DmaLinePort(lineEntries)
        val manualMode = Input(Bool())
        val manualLine = Flipped(new soc.ip.dma.DmaLinePort(lineEntries))
        val blockLineResponse = Input(Bool())
        val lineRequestTag = Output(UInt(2.W))
        val lineResponseTag = Output(UInt(2.W))
        val homeLineRequestTag = Output(UInt(2.W))
        val homeLineResponseTag = Output(UInt(2.W))
        val lineResponseOffer = Output(Bool())
        val lineResponseData = Output(UInt(512.W))
        val lineResponseOfferTag = Output(UInt(2.W))
        val lineRequestData = Output(UInt(512.W))
        val homeLineOffer = Output(Bool())
        val homeLineFire = Output(Bool())
        val homeLineResponse = Output(Bool())
        val lineRequestReady = Output(Bool())
        val tlAValid = Output(Bool())
        val tlAReady = Output(Bool())
        val tlAOpcode = Output(UInt(3.W))
        val tlASource = Output(UInt(4.W))
        val tlAAddress = Output(UInt(64.W))
        val tlASize = Output(UInt(4.W))
        val tlDValid = Output(Bool())
        val tlDReady = Output(Bool())
        val tlDOpcode = Output(UInt(3.W))
        val tlDSource = Output(UInt(4.W))
        val control = Flipped(new RegisterPort)
        val cpu = Flipped(new DataPort)
        val ddrAxi = new soc.ip.axi.Axi4MemoryPort(32, 4)
        val active = Output(Bool())
        val atomicActive = Output(Bool())
        val atomicCpuOffer = Output(Bool())
        val cacheAcquireOffer = Output(Bool())
        val cacheAcquireFire = Output(Bool())
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
    val adapter = Module(new DmaRegisterDataAdapter)
    val cache = CoherentLineCacheModule.build(base, bytes, 512, coherent, 2, cfg, tags)
    val home = Module(new MixedCoherentLineHome(coherent, base, bytes, trackedLines = 512,
        trackedWays = 2, acquireEntries = 2, tagConfig = tags, writebackEntries = 2, mixedReadWrite = true, dmaLineTransfers = lineTransfers, dmaLineEntries = lineEntries))
    val atomic = Module(new AtomicDataMemory(base, bytes, registerResponseOwners = true, dmaLineTransfers = lineTransfers, dmaLineEntries = lineEntries))
    val requests = Module(new DataRequestBuffer(registerHead = true))
    val ordered = Module(new OrderedTileLinkBridge(allowWriteErrors = true, allowPartialWrites = true))
    val arbiter = Module(new TwoMasterTileLinkArbiter(memory))
    val ddr = Module(new TileLinkAxi4Bridge(tlParams = memory.copy(sourceBits = 4), axiAddressWidth = 32,
        axiIdWidth = 4, maxOutstanding = 4, maxOutstandingWrites = 2, maxBurstBeats = 16,
        unorderedResponses = true, axiAddressBase = base, axiWindowBytes = bytes))
    dma.io.control <> io.control
    adapter.io.registers <> dma.io.memory
    require(lineTransfers, "Pipeline diagnostic requires line transfers")
    val automaticLine = dma.io.line.get
    val dl = Wire(new soc.ip.dma.DmaLinePort(lineEntries))
    dl.request.valid := Mux(io.manualMode, io.manualLine.request.valid, automaticLine.request.valid)
    dl.request.bits := Mux(io.manualMode, io.manualLine.request.bits, automaticLine.request.bits)
    automaticLine.request.ready := dl.request.ready && !io.manualMode
    io.manualLine.request.ready := dl.request.ready && io.manualMode
    automaticLine.response.valid := dl.response.valid && !io.manualMode
    automaticLine.response.bits := dl.response.bits
    io.manualLine.response.valid := dl.response.valid && io.manualMode
    io.manualLine.response.bits := dl.response.bits
    dl.response.ready := Mux(io.manualMode, io.manualLine.response.ready, automaticLine.response.ready)
    val al = atomic.io.dmaLine.get
    val ml = atomic.io.memoryLine.get
    val hl = home.io.dmaLine.get
    val useAtomic = io.diagnosticMode === 0.U || io.diagnosticMode === 3.U
    val useOracle = io.diagnosticMode >= 2.U
    al.request.valid := dl.request.valid && useAtomic
    al.request.bits := dl.request.bits
    val finalResponseReady = dl.response.ready && !io.blockLineResponse
    al.response.ready := finalResponseReady && useAtomic
    val downstreamRequest = Mux(useAtomic, ml.request.bits, dl.request.bits)
    val downstreamValid = Mux(useAtomic, ml.request.valid, dl.request.valid)
    val downstreamReady = Mux(useOracle, io.oracle.request.ready, hl.request.ready)
    val downstreamResponse = Mux(useOracle, io.oracle.response.bits, hl.response.bits)
    val downstreamResponseValid = Mux(useOracle, io.oracle.response.valid, hl.response.valid)
    val downstreamResponseReady = Mux(useAtomic, ml.response.ready, finalResponseReady)
    dl.request.ready := Mux(useAtomic, al.request.ready, downstreamReady)
    val finalResponseValid = Mux(useAtomic, al.response.valid, downstreamResponseValid)
    dl.response.valid := finalResponseValid && !io.blockLineResponse
    dl.response.bits := Mux(useAtomic, al.response.bits, downstreamResponse)
    ml.request.ready := downstreamReady && useAtomic
    ml.response.valid := downstreamResponseValid && useAtomic
    ml.response.bits := downstreamResponse
    hl.request.valid := downstreamValid && !useOracle
    hl.request.bits := downstreamRequest
    hl.response.ready := downstreamResponseReady && !useOracle
    io.oracle.request.valid := downstreamValid && useOracle
    io.oracle.request.bits := downstreamRequest
    io.oracle.response.ready := downstreamResponseReady && useOracle
    io.lineRequestTag := dl.request.bits.tag
    io.lineResponseTag := dl.response.bits.tag
    io.homeLineRequestTag := hl.request.bits.tag
    io.homeLineResponseTag := hl.response.bits.tag
    io.lineResponseOffer := finalResponseValid
    io.lineResponseData := dl.response.bits.data
    io.lineResponseOfferTag := dl.response.bits.tag
    io.lineRequestData := dl.request.bits.data
    io.homeLineOffer := hl.request.valid
    io.homeLineFire := hl.request.fire
    io.homeLineResponse := hl.response.fire
    io.lineRequestReady := dl.request.ready
    when(io.diagnosticMode =/= 0.U) {
        assert(!io.cpu.request.valid, "Component bypass is restricted to isolated diagnostics")
    }
    cache.io.upstream <> io.cpu
    cache.io.upstream.request.bits.prefetchNextAllowed := false.B
    cache.io.flushRequest := io.flushRequest
    home.io.drainRequest := (io.flushRequest && cache.io.flushDone) || io.holdLineHome
    io.flushDone := cache.io.flushDone && home.io.drainDone
    atomic.io.cpu <> cache.io.downstream
    atomic.io.dma <> adapter.io.data
    atomic.io.clearReservation := false.B
    requests.io.upstream <> atomic.io.memory
    requests.io.requestCpu := atomic.io.memoryRequestCpu
    home.io.upstream <> requests.io.downstream
    home.io.upstreamRequestCpu := requests.io.downstreamRequestCpu
    home.io.clients(0) <> cache.io.tl
    ordered.io.data <> home.io.downstream
    arbiter.io.masters(0) <> ordered.io.tl
    CoherentHomeUlBoundary.connect(home.io.line, arbiter.io.masters(1))
    ddr.io.tl <> arbiter.io.manager
    io.ddrAxi <> ddr.io.axi
    io.tlAValid := ddr.io.tl.a.valid
    io.tlAReady := ddr.io.tl.a.ready
    io.tlAOpcode := ddr.io.tl.a.bits.opcode
    io.tlASource := ddr.io.tl.a.bits.source
    io.tlAAddress := ddr.io.tl.a.bits.address
    io.tlASize := ddr.io.tl.a.bits.size
    io.tlDValid := ddr.io.tl.d.valid
    io.tlDReady := ddr.io.tl.d.ready
    io.tlDOpcode := ddr.io.tl.d.bits.opcode
    io.tlDSource := ddr.io.tl.d.bits.source
    val atomicActive = RegInit(false.B)
    when(atomic.io.cpu.request.fire && atomic.io.cpu.request.bits.atomic && atomic.io.cpu.request.bits.atomicOp === 0.U) { atomicActive := true.B }
    when(atomic.io.cpu.response.fire) { atomicActive := false.B }
    io.atomicActive := atomicActive
    io.atomicCpuOffer := atomic.io.cpu.request.valid
    io.cacheAcquireOffer := cache.io.tl.a.valid
    io.cacheAcquireFire := cache.io.tl.a.fire
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
    io.lineRequestOffer := dl.request.valid
    io.lineRequestFire := dl.request.fire
    io.lineRequestWrite := dl.request.bits.write
    io.lineRequestAddress := dl.request.bits.address
    io.lineResponseFire := dl.response.fire
    io.lineResponseError := dl.response.bits.error
    io.homeRequestOffer := home.io.upstream.request.valid
    io.homeRequestFire := home.io.upstream.request.fire
    io.homeResponseFire := home.io.upstream.response.fire
}

object DmaPipelineGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new DmaPipelineGsim(true, args.lift(1).map(_.toInt).getOrElse(0), args.lift(2).map(_.toInt).getOrElse(1)), Array("--target-dir", args.head))
}
