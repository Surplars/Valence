package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLParams, TLOpcode}
import soc.core.ooo._
import soc.ip.bus.{RegisterArbiter, RegisterPort}
import soc.ip.dma.{EthernetAxisWord, EthernetPacketDma, MemoryCopyDma}
import soc.ip.tilelink.TwoMasterTileLinkArbiter

/** Real packet and copy engines share the production scalar arbiter, atomic boundary, cache/home, and AXI.
  * Packet DMA remains scalar. C++ independently checks software descriptor generations and byte contents.
  */
class DmaPacketStopGsim(lineTransfers: Boolean = true, lineYieldCycles: Int = 0) extends Module {
    private val base = BigInt("80200000", 16)
    private val bytes = BigInt(2) * 1024 * 1024 * 1024
    private val tags = CacheTagConfig(compact = true, bankedStorage = true)
    private val cfg = CoherentCacheConcurrency(2, 2, 2, overlapWritebackRefill = true)
    private val coherent = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 1)
    private val memory = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val control = Flipped(new RegisterPort)
        val packetControl = Flipped(new RegisterPort)
        val txData = Decoupled(new EthernetAxisWord)
        val txControl = Decoupled(new EthernetAxisWord)
        val rxData = Flipped(Decoupled(new EthernetAxisWord))
        val rxStatus = Flipped(Decoupled(new EthernetAxisWord))
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
    val dma = Module(new MemoryCopyDma(ramBase = base, ramBytes = bytes, lineTransfers = lineTransfers, lineYieldCycles = lineYieldCycles))
    val packet = Module(new EthernetPacketDma(ramBase = base, ramBytes = bytes, postedRxSlots = 4,
        memoryCredits = 4, postedTxSlots = 4))
    val scalarArbiter = Module(new RegisterArbiter)
    val adapter = Module(new DmaRegisterDataAdapter)
    val cache = CoherentLineCacheModule.build(base, bytes, 512, coherent, 2, cfg, tags)
    val home = Module(new MixedCoherentLineHome(coherent, base, bytes, trackedLines = 512,
        trackedWays = 2, acquireEntries = 2, tagConfig = tags, writebackEntries = 2, mixedReadWrite = true, dmaLineTransfers = lineTransfers))
    val atomic = Module(new AtomicDataMemory(base, bytes, registerResponseOwners = true, dmaLineTransfers = lineTransfers))
    val requests = Module(new DataRequestBuffer(registerHead = true))
    val ordered = Module(new OrderedTileLinkBridge(allowWriteErrors = true, allowPartialWrites = true))
    val arbiter = Module(new TwoMasterTileLinkArbiter(memory))
    val ddr = Module(new TileLinkAxi4Bridge(tlParams = memory.copy(sourceBits = 4), axiAddressWidth = 32,
        axiIdWidth = 4, maxOutstanding = 4, maxOutstandingWrites = 2, maxBurstBeats = 16,
        unorderedResponses = true, axiAddressBase = base, axiWindowBytes = bytes))
    dma.io.control <> io.control
    packet.io.control <> io.packetControl
    io.txData <> packet.io.txData
    io.txControl <> packet.io.txControl
    packet.io.rxData <> io.rxData
    packet.io.rxStatus <> io.rxStatus
    scalarArbiter.io.clients(0) <> dma.io.memory
    scalarArbiter.io.clients(1) <> packet.io.memory
    adapter.io.registers <> scalarArbiter.io.memory
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

object DmaPacketStopGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new DmaPacketStopGsim(lineYieldCycles = args.lift(1).map(_.toInt).getOrElse(0)), Array("--target-dir", args.head))
}
