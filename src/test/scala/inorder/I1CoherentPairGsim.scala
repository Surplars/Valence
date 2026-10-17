package inorder

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.core.inorder._
import soc.ip.tilelink.TwoMasterTileLinkArbiter

/** Independent byte-store backing model: one-cycle synchronous reads, bounded
  * response credits, byte enables; no CPU/cache-derived expected values.
  */
class I1CoherenceTestRam(bytes: Int) extends Module {
    val io = IO(new Bundle { val port = Flipped(new I1DataPort) })
    val ram = SyncReadMem(bytes / 8, Vec(8, UInt(8.W)))
    val replies = Module(new Queue(new I1DataResponse, 4, pipe = false, flow = false))
    val pending = RegNext(io.port.request.fire, false.B)
    val count = RegInit(0.U(3.W))
    io.port.request.ready := count < 4.U
    when(io.port.request.fire =/= io.port.response.fire) {
        count := Mux(io.port.request.fire, count + 1.U, count - 1.U)
    }
    val r = io.port.request.bits
    val address = ((r.address - "h80010000".U) >> 3)(log2Ceil(bytes / 8) - 1, 0)
    val data = ram.read(address, io.port.request.fire && !r.write)
    when(io.port.request.fire) {
        assert(r.address >= "h80010000".U && r.address < (BigInt("80010000", 16) + bytes).U && r.size <= 3.U)
        val alignMask = MuxLookup(r.size, 0.U(3.W))(Seq(1.U -> 1.U, 2.U -> 3.U, 3.U -> 7.U))
        assert((r.address(2, 0) & alignMask) === 0.U, "test RAM naturally aligned W/D access")
        assert(!r.atomic)
        when(r.write) {
            ram.write(address, r.data.asTypeOf(Vec(8, UInt(8.W))), r.mask.asBools)
        }
    }
    val writing = RegEnable(r.write, io.port.request.fire)
    replies.io.enq.valid := pending
    replies.io.enq.bits := 0.U.asTypeOf(new I1DataResponse)
    replies.io.enq.bits.data := Mux(writing, 0.U, data.asUInt)
    assert(!pending || replies.io.enq.ready, "test memory response credits overflow")
    io.port.response <> replies.io.deq
}

/** Two actual private caches, bounded I+D-size directory and independent DMA.
  * Cut and uncut models share unchanged C++ traffic and byte expectations.
  */
class I1CoherentPairGsim(cuts: Boolean, ways: Int, cacheBytes: Int = 256,
    bandwidth: Boolean = false, ordered: Boolean = false, lineGrants: Boolean = false,
    missTurnover: Boolean = false, writebackOverlap: Boolean = false,
    readOverlap: Boolean = false) extends Module {
    require(!ordered || cuts)
    val io = IO(new Bundle {
        val hart0 = Flipped(new I1DataPort); val hart1 = Flipped(new I1DataPort)
        val uncached = Flipped(new I1DataPort)
        val flush0 = Input(Bool()); val flush1 = Input(Bool())
        val flushDone0 = Output(Bool()); val flushDone1 = Output(Bool())
        val probe0 = Output(Bool()); val probe1 = Output(Bool())
        val dirtyProbe0 = Output(Bool()); val dirtyProbe1 = Output(Bool())
        val releaseData0 = Output(Bool()); val releaseData1 = Output(Bool())
        val burstWriteBeat = Output(Bool())
        val ordinaryOutstanding = Output(UInt(4.W))
        val readDuringWrite = Output(Bool())
        val acquireDuringRelease = Output(Bool())
        val acquireDuringRead = Output(Bool())
    })
    val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val backingBytes = math.max(4096, 4 * cacheBytes)
    val home = Module(new I1CoherentLineHome(params, bytes = backingBytes, nClients = 2,
        trackedLines = 2 * cacheBytes / 64, trackedWays = 2 * ways,
        parallelQualification = cuts, ordinaryWritePipeline = bandwidth, lineDispatchFlow = bandwidth,
        internalLineGrant = lineGrants, writebackOverlap = writebackOverlap, readOverlap = readOverlap))
    val caches = Seq.fill(2)(Module(new I1CoherentLineCache(bytes = backingBytes, lines = cacheBytes / 64,
        params = params, ways = ways, controlTimingCuts = cuts, orderedDataAdmission = ordered,
        internalLineGrant = lineGrants, missTurnover = missTurnover, writebackOverlap = writebackOverlap)))
    // Observe only accepted/returned native requests, not internal DUT owners.
    // The C++ oracle independently counts its offers and actual responses.
    val ordinaryOutstanding = RegInit(0.U(4.W))
    when(home.io.downstream.request.fire =/= home.io.downstream.response.fire) {
        ordinaryOutstanding := Mux(home.io.downstream.request.fire,
            ordinaryOutstanding + 1.U, ordinaryOutstanding - 1.U)
    }
    io.ordinaryOutstanding := ordinaryOutstanding
    val uncachedCpu = Module(new I1SharedDataArbiter(registerResponseOwners = true))
    val atomic = Module(new I1AtomicDataMemory(bytes = backingBytes, registerResponseOwners = true))
    atomic.io.cpu <> uncachedCpu.io.memory
    atomic.io.dma <> io.uncached
    atomic.io.clearReservation := caches.map(_.io.tl.b.fire).reduce(_ || _)
    for (i <- 0 until 2) {
        val c = caches(i)
        c.io.lineGrant.foreach(_ <> home.io.lineGrants.get(i))
        c.io.upstream <> Seq(io.hart0, io.hart1)(i)
        c.io.flushRequest := Seq(io.flush0, io.flush1)(i)
        if (cuts) {
            val nativeCut = Module(new I1RegisteredDataBoundary(preparePayload = true))
            nativeCut.io.upstream <> c.io.downstream
            uncachedCpu.io.clients(i) <> nativeCut.io.downstream
            val boundary = Module(new I1RegisteredCoherentBoundary(params))
            boundary.io.upstream <> c.io.tl
            home.io.clients(i) <> boundary.io.downstream
        } else {
            uncachedCpu.io.clients(i) <> c.io.downstream
            home.io.clients(i) <> c.io.tl
        }
    }
    io.flushDone0 := caches(0).io.flushDone; io.flushDone1 := caches(1).io.flushDone
    io.probe0 := caches(0).io.tl.b.fire; io.probe1 := caches(1).io.tl.b.fire
    io.dirtyProbe0 := caches(0).io.tl.c.fire && caches(0).io.tl.c.bits.opcode === TLOpcode.ProbeAckData
    io.dirtyProbe1 := caches(1).io.tl.c.fire && caches(1).io.tl.c.bits.opcode === TLOpcode.ProbeAckData
    io.releaseData0 := caches(0).io.tl.c.fire && caches(0).io.tl.c.bits.opcode === TLOpcode.ReleaseData
    io.releaseData1 := caches(1).io.tl.c.fire && caches(1).io.tl.c.bits.opcode === TLOpcode.ReleaseData
    if (cuts) {
        val ownershipCut = Module(new I1RegisteredDataBoundary)
        ownershipCut.io.upstream <> atomic.io.memory
        home.io.upstream <> ownershipCut.io.downstream
    } else home.io.upstream <> atomic.io.memory
    home.io.upstreamRequestCpu := false.B; home.io.drainRequest := false.B
    val bridge = Module(new I1OrderedTileLinkBridge(orderedWrites = true,
        orderedMixedAccesses = true, allowWriteErrors = true))
    if (cuts) {
        val ordinaryCut = Module(new I1RegisteredDataBoundary)
        ordinaryCut.io.upstream <> home.io.downstream
        bridge.io.data <> ordinaryCut.io.downstream
    } else bridge.io.data <> home.io.downstream
    val arbiter = Module(new TwoMasterTileLinkArbiter(params))
    arbiter.io.masters(0) <> bridge.io.tl; arbiter.io.masters(1) <> home.io.line
    io.burstWriteBeat := home.io.line.a.fire &&
        home.io.line.a.bits.opcode === TLOpcode.PutFullData && home.io.line.a.bits.size === 6.U
    // Independent test witness at the real backing TL handshakes.
    val backingWrite = RegInit(false.B)
    when(io.burstWriteBeat) { backingWrite := true.B }
    when(home.io.line.d.fire && home.io.line.d.bits.opcode === TLOpcode.AccessAck) {
        backingWrite := false.B
    }
    io.readDuringWrite := backingWrite && home.io.line.a.fire &&
        home.io.line.a.bits.opcode === TLOpcode.Get && home.io.line.a.bits.size === 6.U
    val releasePending = RegInit(VecInit(Seq.fill(2)(false.B)))
    for (i <- 0 until 2) {
        when(home.io.clients(i).c.fire &&
            home.io.clients(i).c.bits.opcode === TLOpcode.ReleaseData) { releasePending(i) := true.B }
        when(home.io.clients(i).d.fire &&
            home.io.clients(i).d.bits.opcode === TLOpcode.ReleaseAck) { releasePending(i) := false.B }
    }
    io.acquireDuringRelease := releasePending.asUInt.orR && home.io.clients.map(_.a.fire).reduce(_ || _)
    val readOwners = RegInit(0.U(2.W))
    val newReads = PopCount(home.io.clients.map(_.a.fire))
    val finishedReads = PopCount(home.io.clients.map(_.e.fire))
    readOwners := readOwners + newReads - finishedReads
    io.acquireDuringRead := readOwners =/= 0.U && newReads =/= 0.U
    assert(readOwners <= 2.U, "Home exceeded the existing two read/release contexts")
    val manager = Module(new I1TestRamAdapter(params = params.copy(sourceBits = 4),
        burstEnabled = true, burstBytes = backingBytes))
    manager.io.tl <> arbiter.io.manager
    val ram = Module(new I1CoherenceTestRam(backingBytes))
    ram.io.port <> manager.io.memory
}

object I1CoherentPairGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1CoherentPairGsim(args.contains("--cuts"),
        if (args.contains("--two-way")) 2 else 1,
        args.find(_.startsWith("--cache-bytes=")).map(_.stripPrefix("--cache-bytes=").toInt).getOrElse(256),
        bandwidth = args.contains("--bandwidth"), ordered = args.contains("--ordered-admission"),
        lineGrants = args.contains("--line-grants"), missTurnover = args.contains("--miss-turnover"),
        writebackOverlap = args.contains("--writeback-overlap"), readOverlap = args.contains("--read-overlap")),
        Array("--target-dir", args.head))
}
