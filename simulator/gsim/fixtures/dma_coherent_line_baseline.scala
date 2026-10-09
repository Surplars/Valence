package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLParams, TLOpcode}
import soc.core.ooo._
import soc.ip.bus.RegisterPort
import soc.ip.dma.MemoryCopyDma
import soc.ip.tilelink.TwoMasterTileLinkArbiter

/** Source-bound DMA/cache/home/AXI fixture. CPU requests and all memory bytes are checked independently in C++. */
class DmaCoherentLineGsim(lineTransfers: Boolean = false) extends Module {
    require(!lineTransfers, "Exact e8520ab baseline has no line extension")
    private val base = BigInt("80200000", 16)
    private val bytes = BigInt(2) * 1024 * 1024 * 1024
    private val tags = CacheTagConfig(compact = true, bankedStorage = true)
    private val cfg = CoherentCacheConcurrency(2, 2, 2, overlapWritebackRefill = true)
    private val coherent = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 1)
    private val memory = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val control = Flipped(new RegisterPort)
        val cpu = Flipped(new DataPort)
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
    val dma = Module(new MemoryCopyDma(ramBase = base, ramBytes = bytes))
    val adapter = Module(new DmaRegisterDataAdapter)
    val cache = CoherentLineCacheModule.build(base, bytes, 512, coherent, 2, cfg, tags)
    val home = Module(new MixedCoherentLineHome(coherent, base, bytes, trackedLines = 512,
        trackedWays = 2, acquireEntries = 2, tagConfig = tags, writebackEntries = 2, mixedReadWrite = true))
    val atomic = Module(new AtomicDataMemory(base, bytes, registerResponseOwners = true))
    val requests = Module(new DataRequestBuffer(registerHead = true))
    val ordered = Module(new OrderedTileLinkBridge(allowWriteErrors = true, allowPartialWrites = true))
    val arbiter = Module(new TwoMasterTileLinkArbiter(memory))
    val ddr = Module(new TileLinkAxi4Bridge(tlParams = memory.copy(sourceBits = 4), axiAddressWidth = 32,
        axiIdWidth = 4, maxOutstanding = 4, maxOutstandingWrites = 2, maxBurstBeats = 16,
        unorderedResponses = true, axiAddressBase = base, axiWindowBytes = bytes))
    dma.io.control <> io.control
    adapter.io.registers <> dma.io.memory

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
    io.lineRequestOffer := false.B
    io.lineRequestFire := false.B
    io.lineRequestWrite := false.B
    io.lineRequestAddress := 0.U
    io.lineResponseFire := false.B
    io.lineResponseError := false.B
    io.homeRequestOffer := home.io.upstream.request.valid
    io.homeRequestFire := home.io.upstream.request.fire
    io.homeResponseFire := home.io.upstream.response.fire
}

object DmaCoherentLineGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new DmaCoherentLineGsim(args.lift(1).contains("1")), Array("--target-dir", args.head))
}
