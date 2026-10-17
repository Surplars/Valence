package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink._
import soc.core.ooo._
import soc.ip.tilelink._

/** Protocol fixture: actual acquire engine + isolated Home + actual AXI bridge.
  * The host is a coherent client protocol oracle, not a CPU or private cache.
  * Holds must be asserted before an offer and remain until it is accepted.
  */
class FullLineHomeGsim(enabled: Boolean, internal: Boolean) extends Module {
    val p = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 2)
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new LineAcquireRequest(64, 16)))
        val response = Decoupled(new LineAcquireResponse(16))
        val release = Flipped(Decoupled(new TLBundleC(p)))
        val releaseAck = Decoupled(new TLBundleD(p))
        val holdA = Input(Bool()); val holdD = Input(Bool())
        val holdLine = Input(Bool()); val holdE = Input(Bool())
        val holdC = Input(Bool())
        // Fault shim is solely an engine negative-control boundary. It does not
        // turn a successful Home owner into a denied directory transaction.
        val corruptD = Input(Bool()); val wrongOpcodeD = Input(Bool())
        val deniedD = Input(Bool()); val badCapD = Input(Bool())
        val drain = Input(Bool()); val drained = Output(Bool())
        val axi = new soc.ip.axi.Axi4MemoryPort(32, 4)
        val a = Output(Valid(new TLBundleA(p)))
        val d = Output(Valid(new TLBundleD(p)))
        val c = Output(Valid(new TLBundleC(p)))
        val e = Output(Valid(new TLBundleE(p)))
        val line = Output(Valid(new LineGrant(p)))
        val read = Output(Valid(new LineFillRequest(64, 2)))
        val aOffered = Output(Bool()); val dOffered = Output(Bool())
        val cOffered = Output(Bool()); val eOffered = Output(Bool())
        val lineOffered = Output(Bool())
    })
    val home = Module(new FullLineMixedCoherentLineHome(p, base = 4096, bytes = 4096,
        trackedLines = 16, trackedWays = 2, acquireEntries = 2,
        tagConfig = CacheTagConfig(compact = true, bankedStorage = true),
        writebackEntries = 2, mixedReadWrite = true, distinctWayRelease = true,
        lineTransferDispatchFlow = true, lineReadChannel = true,
        internalLineGrant = internal, memoryScheduleOverlap = true,
        futureWayReservation = true, permissionOnlyAllocation = enabled))
    val engine = Module(new TileLinkLineAcquireEngine(p, entries = 2, tagBits = 16,
        internalLineGrant = internal))
    val port = home.io.clients(0)
    engine.io.request <> io.request
    io.response <> engine.io.response
    port.a.bits := engine.io.a.bits
    port.a.valid := engine.io.a.valid && !io.holdA
    engine.io.a.ready := port.a.ready && !io.holdA
    port.e.bits := engine.io.e.bits
    port.e.valid := engine.io.e.valid && !io.holdE
    engine.io.e.ready := port.e.ready && !io.holdE
    port.c.bits := io.release.bits
    port.c.valid := io.release.valid && !io.holdC
    io.release.ready := port.c.ready && !io.holdC
    port.b.ready := false.B
    assert(!port.b.valid, "B0 has no maintenance request requiring a cache probe")
    val isAck = port.d.bits.opcode === TLOpcode.ReleaseAck
    io.releaseAck.valid := port.d.valid && isAck && !io.holdD
    io.releaseAck.bits := port.d.bits
    engine.io.d.valid := port.d.valid && !isAck && !io.holdD
    engine.io.d.bits := port.d.bits
    engine.io.d.bits.denied := port.d.bits.denied || io.deniedD
    engine.io.d.bits.corrupt := port.d.bits.corrupt || io.corruptD
    engine.io.d.bits.opcode := Mux(io.wrongOpcodeD, TLOpcode.AccessAck, port.d.bits.opcode)
    engine.io.d.bits.param := Mux(io.badCapD, 3.U, port.d.bits.param)
    port.d.ready := !io.holdD && Mux(isAck, io.releaseAck.ready, engine.io.d.ready)
    io.line.valid := false.B; io.line.bits := 0.U.asTypeOf(io.line.bits)
    io.lineOffered := false.B
    if (internal) {
        val g = home.io.lineGrants.get(0)
        val r = engine.io.lineGrant.get
        r.bits := g.bits; r.valid := g.valid && !io.holdLine
        g.ready := r.ready && !io.holdLine
        io.line.valid := g.fire; io.line.bits := g.bits
        io.lineOffered := g.valid
    }
    home.io.upstream.request.valid := false.B
    home.io.upstream.request.bits := 0.U.asTypeOf(home.io.upstream.request.bits)
    home.io.upstream.response.ready := true.B
    home.io.upstreamRequestCpu := false.B
    home.io.downstream.request.ready := false.B
    home.io.downstream.response.valid := false.B
    home.io.downstream.response.bits := 0.U.asTypeOf(home.io.downstream.response.bits)
    assert(!home.io.downstream.request.valid, "B0 unexpected scalar backing request")
    home.io.drainRequest := io.drain; io.drained := home.io.drainDone
    val mem = p.copy(sinkBits = 1)
    val ddr = Module(new TileLinkAxi4Bridge(tlParams = mem, axiAddressWidth = 32,
        axiIdWidth = 4, maxOutstanding = 4, maxBurstBeats = 8,
        maxOutstandingWrites = 2, unorderedResponses = true,
        lineReadChannel = true, axiAddressBase = 4096, axiWindowBytes = 4096))
    CoherentHomeUlBoundary.connect(home.io.line, ddr.io.tl)
    ddr.io.lineRead.get <> home.io.lineRead.get
    io.axi <> ddr.io.axi
    io.a.valid := port.a.fire; io.a.bits := port.a.bits; io.aOffered := port.a.valid
    io.d.valid := port.d.fire; io.d.bits := port.d.bits; io.dOffered := port.d.valid
    io.c.valid := port.c.fire; io.c.bits := port.c.bits; io.cOffered := port.c.valid
    io.e.valid := port.e.fire; io.e.bits := port.e.bits; io.eOffered := port.e.valid
    io.read.valid := home.io.lineRead.get.request.fire
    io.read.bits.address := home.io.lineRead.get.request.bits.address
    io.read.bits.tag := home.io.lineRead.get.request.bits.tag
    when(io.read.valid) { assert(home.io.lineRead.get.request.bits.tag < 2.U, "B0 read tag must be an acquire owner") }
}
object FullLineHomeGsimMain extends App {
    require(args.length == 3, "output directory, enabled 0/1, internalLineGrant 0/1")
    ChiselStage.emitCHIRRTLFile(new FullLineHomeGsim(args(1) == "1", args(2) == "1"),
        Array("--target-dir", args(0)))
}
