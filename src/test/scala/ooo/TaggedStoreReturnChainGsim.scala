package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.bus.tilelink.TLParams
import soc.core.ooo._
import soc.ip.bus.RegisterPort
import soc.ip.tilelink.TwoMasterTileLinkArbiter

/** Real registered request/return chain. Authority inputs have the same bounded
  * MemoryOperation contract as BoundHeadStoreOverlapGsim; this is not a ROB test.
  * The host owns full-token, VA/PA, bytes, accepted-handle and cancellation oracles.
  * Only external protocol stalls and ordinary peripheral/PTE/backing replies are driven.
  */
class TaggedStoreReturnChainGsim(enabled: Boolean) extends Module {
    val p = PendingStoreProofFixture.params().copy(boundHeadStoreOverlap = true,
        storeBufferEntries = 2, taggedStoreReturns = enabled, dataNextLinePrefetch = true,
        registeredStoreResponseOwners = true, registeredLocalStoreResponses = true)
    private val base = p.speculativeRamBase
    private val bytes = p.speculativeRamBytes
    private val cfg = CoherentCacheConcurrency(2, 2, 2, true, independentDemandAdmission = true)
    private val coherent = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = cfg.sinkBits)
    private val memory = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val start = Flipped(Decoupled(new MemoryOperation(p)))
        val parallel = Input(Bool())
        val qualified = Input(Bool())
        val cancel = Input(UInt(4.W))
        val complete = Decoupled(new BackendCompletion(p))
        val live = Output(UInt(4.W))
        val owner0 = Output(new RobToken(p)); val owner1 = Output(new RobToken(p))
        val owner2 = Output(new RobToken(p)); val owner3 = Output(new RobToken(p))
        val chosen = Output(UInt(2.W))
        val overlapAccepted = Output(Bool())
        val discarded = Output(Bool())
        val epoch = Output(UInt(32.W)); val stable = Output(Bool())
        val vm = Input(new VmCsrState)
        val pmpCfg = Input(UInt(8.W)); val pmpAddress = Input(UInt(54.W))
        val precheckFlush = Input(Bool())
        val pte = new SvPteReadPort
        val mmio0 = new RegisterPort; val mmio1 = new RegisterPort
        val dma = Flipped(new DataPort)
        val ddrAxi = new soc.ip.axi.Axi4MemoryPort(32, 4)
        val holdQueue = Input(Bool())
        val holdEnqueue = Input(Bool())
        val holdCacheRequest = Input(Bool())
        val holdCacheResponse = Input(Bool())
        val queueFire = Output(Bool())
        val queueOwner = Output(new RobToken(p))
        val queueHandle = Output(UInt(3.W))
        val queueAddress = Output(UInt(64.W))
        val physicalFire = Output(Bool())
        val physical = Output(new DataRequest(p.dataReturnHandleBits))
        val physicalResponseFire = Output(Bool())
        val cacheFire = Output(Bool())
        val cacheRequest = Output(new DataRequest(p.dataReturnHandleBits))
        val cacheHit = Output(Bool())
        val independentStoreWrite = Output(Bool())
        val cacheResponseValid = Output(Bool()); val cacheResponseReady = Output(Bool())
        val cacheResponse = Output(new DataResponse(p.dataReturnHandleBits))
        val lsuResponseFire = Output(Bool())
        val lsuResponse = Output(new DataResponse(p.dataReturnHandleBits))
        val idle = Output(Bool())
        val flushRequest = Input(Bool()); val flushDone = Output(Bool())
    })
    val lsu = Module(new ParallelLoadStoreUnit(p, canonicalHandoff = true))
    val requests = Module(new Queue(new DataRequest(p.dataReturnHandleBits), p.memoryEntries,
        pipe = false, flow = false))
    val origins = Module(new Queue(Valid(new CanonicalStoreOrigin(p)), p.memoryEntries,
        pipe = false, flow = false))
    val frozen = Module(new Queue(Valid(new FrozenStoreProof), p.memoryEntries, pipe = false, flow = false))
    val stores = Module(new StoreBuffer(p))
    val responses = Module(new DataResponseBuffer(registerPayload = true, registerHead = true,
        returnConfig = p.cpuReturnConfig))
    val adapter = Module(new DataTranslationAdapter(p, registerCheckedRequests = true))
    val translation = Module(new SvTranslationService(3, 8, 16, loadPeek = true))
    val router0 = Module(new ParallelRegisterRouter(Seq(BigInt("1000", 16) -> BigInt(256)),
        bypassMemoryShift = true, returnConfig = p.cpuReturnConfig))
    val router1 = Module(new ParallelRegisterRouter(Seq(BigInt("2000", 16) -> BigInt(256)),
        bypassMemoryShift = true, returnConfig = p.cpuReturnConfig))
    val cache = CoherentLineCacheModule.build(base, bytes, 8, coherent, 2, cfg,
        returnConfig = p.cpuReturnConfig)
    val home = CoherentLineHomeModule.build(coherent, base, bytes, trackedLines = 8,
        trackedWays = 2, acquireEntries = 2, writebackEntries = 2, mixedReadWrite = true)
    val atomic = Module(new AtomicDataMemory(base, bytes, registerResponseOwners = true))
    val homeRequests = Module(new DataRequestBuffer(registerHead = true))
    val ordered = Module(new OrderedTileLinkBridge(allowWriteErrors = true, allowPartialWrites = true))
    val arbiter = Module(new TwoMasterTileLinkArbiter(memory))
    val ddr = Module(new TileLinkAxi4Bridge(tlParams = memory.copy(sourceBits = 4),
        axiAddressWidth = 32, axiIdWidth = 4, maxOutstanding = 4, maxBurstBeats = 8,
        maxOutstandingWrites = 2, unorderedResponses = true, axiAddressBase = base, axiWindowBytes = bytes))

    lsu.io.start <> io.start
    lsu.io.parallel := io.parallel
    lsu.io.boundHeadStoreOverlapQualified.get := io.qualified
    lsu.io.relaxStoreOwner.get := 0.U.asTypeOf(lsu.io.relaxStoreOwner.get)
    lsu.io.issueDestination.foreach(_ := 0.U.asTypeOf(lsu.io.issueDestination.get))
    lsu.io.cancel := VecInit((0 until 4).map(i => io.cancel(i)))
    lsu.io.fastStoreRetire := false.B; lsu.io.fastLoadRetire := false.B
    io.complete <> lsu.io.complete
    io.live := lsu.io.live.asUInt
    Seq(io.owner0, io.owner1, io.owner2, io.owner3).zipWithIndex.foreach { case (out, i) => out := lsu.io.owner(i) }
    io.chosen := BoringUtils.bore(lsu.chosen)
    io.overlapAccepted := lsu.io.boundHeadStoreOverlapAccepted.get
    io.discarded := lsu.io.discarded
    requests.io.enq <> lsu.io.memory.request
    requests.io.enq.valid := lsu.io.memory.request.valid && !io.holdEnqueue
    lsu.io.memory.request.ready := requests.io.enq.ready && !io.holdEnqueue
    origins.io.enq.valid := requests.io.enq.fire; origins.io.enq.bits := lsu.io.canonicalStoreOrigin.get
    frozen.io.enq.valid := requests.io.enq.fire; frozen.io.enq.bits := lsu.io.frozenStoreProof.get
    origins.io.deq.ready := requests.io.deq.fire; frozen.io.deq.ready := requests.io.deq.fire
    stores.io.upstream.request <> requests.io.deq
    stores.io.upstream.request.valid := requests.io.deq.valid && !io.holdQueue
    requests.io.deq.ready := stores.io.upstream.request.ready && !io.holdQueue
    stores.io.upstream.request.bits.size := Mux(requests.io.deq.valid, requests.io.deq.bits.size, 0.U)
    stores.io.upstreamCanonicalStoreOrigin.get := origins.io.deq.bits
    stores.io.upstreamCanonicalStoreOrigin.get.valid := stores.io.upstream.request.valid && origins.io.deq.bits.valid
    stores.io.upstreamFrozenStoreProof.get := frozen.io.deq.bits
    stores.io.upstreamFrozenStoreProof.get.valid := stores.io.upstream.request.valid && frozen.io.deq.bits.valid
    assert(origins.io.deq.valid === requests.io.deq.valid && frozen.io.deq.valid === requests.io.deq.valid)
    when(requests.io.enq.fire) { assert(origins.io.enq.ready && frozen.io.enq.ready) }
    lsu.io.memory.response <> stores.io.upstream.response
    stores.io.fastStore.valid := false.B; stores.io.fastStore.bits := 0.U.asTypeOf(stores.io.fastStore.bits)
    responses.io.upstream <> stores.io.memory
    adapter.io.virtual <> responses.io.downstream
    adapter.io.canonicalStoreOrigin.get := stores.io.memoryCanonicalStoreOrigin.get
    adapter.io.frozenStoreProof.get := stores.io.memoryFrozenStoreProof.get
    adapter.io.vmState := io.vm
    val pmp = PendingStoreProofFixture.pmp(io.pmpCfg, io.pmpAddress)
    adapter.io.pmpState := pmp; translation.io.pmpState := pmp
    translation.io.client <> adapter.io.translation
    translation.io.loadPeek.get <> adapter.io.translationPeek.get
    adapter.io.precheckFlush.get := io.precheckFlush
    translation.io.flush := io.precheckFlush
    adapter.io.loadPrecheck.get.request.valid := false.B
    adapter.io.loadPrecheck.get.request.bits := 0.U.asTypeOf(adapter.io.loadPrecheck.get.request.bits)
    io.pte <> translation.io.memory
    io.epoch := adapter.io.loadPrecheck.get.epoch; io.stable := adapter.io.loadPrecheck.get.stable
    router0.io.upstream <> adapter.io.physical
    router1.io.upstream <> router0.io.memory
    io.mmio0 <> router0.io.registers(0); io.mmio1 <> router1.io.registers(0)
    cache.io.upstream <> router1.io.memory
    cache.io.upstream.request.valid := router1.io.memory.request.valid && !io.holdCacheRequest
    router1.io.memory.request.ready := cache.io.upstream.request.ready && !io.holdCacheRequest
    router1.io.memory.response.valid := cache.io.upstream.response.valid && !io.holdCacheResponse
    cache.io.upstream.response.ready := router1.io.memory.response.ready && !io.holdCacheResponse
    atomic.io.cpu <> cache.io.downstream; atomic.io.dma <> io.dma; atomic.io.clearReservation := false.B
    homeRequests.io.upstream <> atomic.io.memory; homeRequests.io.requestCpu := atomic.io.memoryRequestCpu
    home.io.upstream <> homeRequests.io.downstream; home.io.upstreamRequestCpu := homeRequests.io.downstreamRequestCpu
    home.io.clients(0) <> cache.io.tl
    ordered.io.data <> home.io.downstream
    arbiter.io.masters(0) <> ordered.io.tl
    CoherentHomeUlBoundary.connect(home.io.line, arbiter.io.masters(1))
    ddr.io.tl <> arbiter.io.manager; io.ddrAxi <> ddr.io.axi
    cache.io.flushRequest := io.flushRequest
    home.io.drainRequest := io.flushRequest && cache.io.flushDone
    io.flushDone := cache.io.flushDone && home.io.drainDone
    io.idle := !lsu.io.busy && !stores.io.busy && responses.io.idle && adapter.io.idle && translation.io.idle &&
        !requests.io.deq.valid
    def heldRequest(port: DecoupledIO[DataRequest]): Unit = {
        val held = RegNext(port.valid && !port.ready, false.B)
        val saved = RegEnable(port.bits, port.valid && !port.ready)
        when(held) { assert(port.valid && port.bits.asUInt === saved.asUInt, "test boundary withdrew held request") }
    }
    heldRequest(requests.io.enq)
    heldRequest(stores.io.upstream.request)
    heldRequest(cache.io.upstream.request)
    CpuReturnTransport.held(router1.io.memory.response)
    io.queueFire := requests.io.enq.fire
    io.queueOwner := lsu.io.requestOwner.bits
    io.queueHandle := requests.io.enq.bits.returnHandle.getOrElse(0.U)
    io.queueAddress := requests.io.enq.bits.address
    io.physicalFire := adapter.io.physical.request.fire; io.physical := adapter.io.physical.request.bits
    io.physicalResponseFire := adapter.io.physical.response.fire
    io.cacheFire := cache.io.upstream.request.fire; io.cacheRequest := cache.io.upstream.request.bits
    io.cacheHit := cache.io.hit
    val independentDemand = BoringUtils.bore(cache.asInstanceOf[NonBlockingCoherentLineCache].observationIndependentDemand)
    io.independentStoreWrite := independentDemand(2)
    io.cacheResponseValid := cache.io.upstream.response.valid
    io.cacheResponseReady := cache.io.upstream.response.ready
    io.cacheResponse := cache.io.upstream.response.bits
    io.lsuResponseFire := lsu.io.memory.response.fire; io.lsuResponse := lsu.io.memory.response.bits
}
object TaggedStoreReturnChainGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)))
    ChiselStage.emitCHIRRTLFile(new TaggedStoreReturnChainGsim(args(1) == "1"), Array("--target-dir", args.head))
}
