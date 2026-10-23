package soc.core.inorder

import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.ip.bus.TwoEntryRegisterQueue

/** Physical beat lanes, except atomic operands/results are right-justified.
  * No dependency on OoO decode, ROB, LSU or architectural control.
  */
class I1DataRequest extends soc.ip.memory.NativeMemoryRequest()
class I1DataResponse extends soc.ip.memory.NativeMemoryResponse()
class I1DataPort extends Bundle {
    val request = Decoupled(new I1DataRequest)
    val response = Flipped(Decoupled(new I1DataResponse))
}

/** Native request/reply timing boundary, both directions occupancy-only.
  * II=1, minimum +1 request/+1 reply cycle; never acknowledges a write before
  * the real downstream response. No extra MSHR or transaction identity.
  */
class I1RegisteredDataBoundary(preparePayload: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val upstream = Flipped(new I1DataPort); val downstream = new I1DataPort
    })
    val requests = Module(new I1PreparedRegisterQueue(new I1DataRequest, preparePayload))
    val replies = Module(new TwoEntryRegisterQueue(new I1DataResponse))
    requests.io.enq <> io.upstream.request; io.downstream.request <> requests.io.deq
    replies.io.enq <> io.downstream.response; io.upstream.response <> replies.io.deq
}

class I1PrefetchEvents extends Bundle {
    val candidate = Bool(); val allocated = Bool(); val useful = Bool(); val error = Bool()
    val missOwners = UInt(3.W); val releaseOwners = UInt(3.W)
}
abstract class I1CoherentLineCacheModule(params: TLParams,
    trustedReadOnlyCacheability: Boolean = false, internalLineGrant: Boolean = false,
    reportQuiescence: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val upstream = Flipped(new I1DataPort); val downstream = new I1DataPort
        val tl = new TLBundle(params)
        val lineGrant = if (internalLineGrant)
            Some(Flipped(Decoupled(new soc.ip.tilelink.LineGrant(params)))) else None
        val flushRequest = Input(Bool()); val flushDone = Output(Bool())
        val quiescent = if (reportQuiescence) Some(Output(Bool())) else None
        val quiescenceRequestPending = if (reportQuiescence) Some(Input(Bool())) else None
        val prefetchBusy = Output(Bool()); val prefetch = Output(new I1PrefetchEvents)
        val hit = Output(Bool()); val miss = Output(Bool()); val profile = Output(new I1CoherentCacheProfile)
        val readCacheable = if (trustedReadOnlyCacheability) Some(Input(Bool())) else None
        val fetchClasses = Output(UInt(8.W))
    })
    io.fetchClasses := 0.U
    io.prefetch := 0.U.asTypeOf(new I1PrefetchEvents)
}
abstract class I1CoherentLineHomeModule(params: TLParams, nClients: Int,
    lineReadChannel: Boolean = false, internalLineGrant: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val upstream = Flipped(new I1DataPort); val downstream = new I1DataPort
        val clients = Vec(nClients, Flipped(new TLBundle(params)))
        val lineGrants = if (internalLineGrant)
            Some(Vec(nClients, Decoupled(new soc.ip.tilelink.LineGrant(params)))) else None
        val line = new TLBundle(params)
        val lineRead = if (lineReadChannel) Some(new soc.ip.tilelink.LineReadMemoryPort(params.addrWidth)) else None
        val upstreamRequestCpu = Input(Bool())
        val drainRequest = Input(Bool()); val drainDone = Output(Bool())
    })
}

/** Only the request is buffered. The existing DDR slot retains the entire
  * response until Home accepts it; do not add another512-bit response FIFO.
  */
class I1RegisteredLineReadRequestBoundary extends Module {
    val io = IO(new Bundle {
        val upstream = Flipped(new soc.ip.tilelink.LineReadMemoryPort())
        val downstream = new soc.ip.tilelink.LineReadMemoryPort()
    })
    val requests = Module(new TwoEntryRegisterQueue(new soc.ip.tilelink.LineFillRequest(64, 8)))
    requests.io.enq <> io.upstream.request
    io.downstream.request <> requests.io.deq
    io.upstream.response <> io.downstream.response
}

/** Independent occupancy-only beat FIFOs on ALL five TL-C channels.
  * +1 cycle/channel, II=1; no transaction/source/sink ownership is invented.
  * C/B/E must progress independently of A/D to avoid probe/acquire deadlock.
  */
class I1RegisteredCoherentBoundary(params: TLParams) extends Module {
    val io = IO(new Bundle {
        val upstream = Flipped(new TLBundle(params)); val downstream = new TLBundle(params)
    })
    val a = Module(new TwoEntryRegisterQueue(new TLBundleA(params)))
    val b = Module(new TwoEntryRegisterQueue(new TLBundleB(params)))
    val c = Module(new TwoEntryRegisterQueue(new TLBundleC(params)))
    val d = Module(new TwoEntryRegisterQueue(new TLBundleD(params)))
    val e = Module(new TwoEntryRegisterQueue(new TLBundleE(params)))
    a.io.enq <> io.upstream.a; io.downstream.a <> a.io.deq
    b.io.enq <> io.downstream.b; io.upstream.b <> b.io.deq
    c.io.enq <> io.upstream.c; io.downstream.c <> c.io.deq
    d.io.enq <> io.downstream.d; io.upstream.d <> d.io.deq
    e.io.enq <> io.upstream.e; io.downstream.e <> e.io.deq
}

/** ISA-independent native/cache adapter. Atomics bypass the private cache and
  * execute at the shared CPU/DMA exclusion point, AFTER translation/PMP.
  */
class I1CoherentWordCache(p: FiveStageConfig, bytes: Int, readOnly: Boolean = false,
    trustedReadOnlyCacheability: Boolean = false, reportMaintenance: Boolean = false,
    reportQuiescence: Boolean = false) extends Module {
    require(p.xlen == 64 && p.cacheLineBytes == 64 && bytes >= 128)
    val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new FiveStageDataRequest(p)))
        val response = Decoupled(new FiveStageDataResponse(p))
        val invalidate = Input(Bool()); val hit = Output(Bool()); val miss = Output(Bool())
        val invalidateDone = if (reportMaintenance) Some(Output(Bool())) else None
        val quiescent = if (reportQuiescence) Some(Output(Bool())) else None
        val quiescenceRequestPending = if (reportQuiescence) Some(Input(Bool())) else None
        val tl = new TLBundle(params); val uncached = new I1DataPort
        val lineGrant = if (p.coherentLineGrants)
            Some(Flipped(Decoupled(new soc.ip.tilelink.LineGrant(params)))) else None
        val readCacheable = if (trustedReadOnlyCacheability) Some(Input(Bool())) else None
    })
    val cache = Module(new I1CoherentLineCache(p.cacheableBase, p.cacheableBytes, bytes / 64, params,
        ways = p.coherentCacheWays, tagConfig = soc.core.ooo.CacheTagConfig.Aperture,
        controlTimingCuts = p.coherentControlCuts,
        orderedReadOnly = readOnly && p.coherentControlCuts,
        orderedDataAdmission = !readOnly && p.coherentBandwidth,
        trustedReadOnlyCacheability = trustedReadOnlyCacheability,
        fetchPredecode = readOnly && p.cacheFetchPredecode,
        internalLineGrant = p.coherentLineGrants,
        missTurnover = !readOnly && p.coherentMissTurnover,
        writebackOverlap = p.coherentWritebackOverlap, reportQuiescence = reportQuiescence))
    cache.io.quiescenceRequestPending.foreach(_ := io.quiescenceRequestPending.get)
    cache.io.lineGrant.foreach(_ <> io.lineGrant.get)
    cache.io.readCacheable.foreach(_ := io.readCacheable.get)
    val maintenance = RegInit(false.B)
    when(io.invalidate) { maintenance := true.B }
    when(cache.io.flushDone && !io.invalidate) { maintenance := false.B }
    cache.io.flushRequest := maintenance || io.invalidate
    io.invalidateDone.foreach(_ := cache.io.flushDone && maintenance)
    val r = io.request.bits
    cache.io.upstream.request.valid := io.request.valid
    io.request.ready := cache.io.upstream.request.ready
    cache.io.upstream.request.bits := 0.U.asTypeOf(new I1DataRequest)
    cache.io.upstream.request.bits.address := r.address
    cache.io.upstream.request.bits.write := (if (readOnly) false.B else r.write)
    cache.io.upstream.request.bits.size := r.size
    cache.io.upstream.request.bits.data := Mux(r.atomic, r.data >> Cat(r.address(2, 0), 0.U(3.W)), r.data)
    val bytesMask = MuxLookup(r.size, 1.U(8.W))(Seq(1.U -> 3.U, 2.U -> 15.U, 3.U -> 255.U))
    cache.io.upstream.request.bits.mask := Mux(r.write, r.mask, (bytesMask << r.address(2, 0))(7, 0))
    cache.io.upstream.request.bits.atomic := (if (readOnly) false.B else r.atomic)
    if (readOnly) {
        when(io.request.valid) { assert(!r.write && !r.atomic, "instruction cache cannot issue writes or AMOs") }
    }
    cache.io.upstream.request.bits.atomicOp := r.atomicOperation
    cache.io.upstream.request.bits.uncached := r.noAllocate
    // Cache hit-under-miss replies remain in order. Keep the atomic lane
    // metadata with every accepted native owner, not a live request bus.
    val metadata = if (p.coherentControlCuts) Module(new I1PreparedMetadataQueue(4, 4)).io
        else Module(new Queue(UInt(4.W), 4, pipe = false, flow = false)).io
    metadata.enq.valid := io.request.fire
    metadata.enq.bits := Cat(r.atomic && r.atomicOperation =/= 3.U, r.address(2, 0))
    assert(!metadata.enq.valid || metadata.enq.ready, "coherent native metadata overflow")
    io.response.valid := cache.io.upstream.response.valid && metadata.deq.valid
    io.response.bits := 0.U.asTypeOf(new FiveStageDataResponse(p))
    val shiftAtomicReply = metadata.deq.bits(3)
    val atomicReplyShift = Cat(metadata.deq.bits(2, 0), 0.U(3.W))
    io.response.bits.data := (if (p.coherentControlCuts) cache.io.upstream.response.bits.data else
        Mux(shiftAtomicReply, cache.io.upstream.response.bits.data << atomicReplyShift,
            cache.io.upstream.response.bits.data))
    io.response.bits.error := cache.io.upstream.response.bits.error
    io.response.bits.pageFault := cache.io.upstream.response.bits.pageFault
    io.response.bits.parcelClasses.foreach(_ := (if (readOnly) cache.io.fetchClasses else 0.U))
    cache.io.upstream.response.ready := io.response.ready && metadata.deq.valid
    metadata.deq.ready := io.response.fire
    io.quiescent.foreach(_ := cache.io.quiescent.get && metadata.count === 0.U)
    io.tl <> cache.io.tl; io.uncached <> cache.io.downstream
    if (p.coherentControlCuts) {
        // Atomics are always native/bypass. Format their payload BEFORE the
        // cache reply mux, not through an atomic lane barrel on every cached
        // ordinary load and every IT/DT page-table response.
        cache.io.downstream.response.bits.data := Mux(shiftAtomicReply,
            io.uncached.response.bits.data << atomicReplyShift, io.uncached.response.bits.data)
        when(cache.io.downstream.response.fire) {
            assert(metadata.deq.valid, "native atomic reply lost its accepted lane owner")
        }
    }
    io.hit := cache.io.hit; io.miss := cache.io.miss
}
