package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import java.nio.file.{Files, Paths}
import soc.bus.tilelink.{TLParams, TLOpcode}
import soc.core.ooo.{CoherentLineCache, CoherentLineHome, DataPort, DataResponse, OrderedTileLinkBridge,
    SynchronousDataRam, TileLinkDataRamAdapter}
import soc.ip.tilelink.TwoMasterTileLinkArbiter

/** Two independent private TL-C clients and an uncached agent sharing one 64-byte-line home. */
class TwoHartCoherentGsim extends Module {
    val io = IO(new Bundle {
        val hart0 = Flipped(new DataPort)
        val hart1 = Flipped(new DataPort)
        val uncached = Flipped(new DataPort)
        val probe0 = Output(Bool())
        val probe1 = Output(Bool())
        val dirtyProbe0 = Output(Bool())
        val dirtyProbe1 = Output(Bool())
        val releaseData0 = Output(Bool())
        val releaseData1 = Output(Bool())
        val burstWriteBeat = Output(Bool())
    })
    val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val home = Module(new CoherentLineHome(params, bytes = 4096, nClients = 2))
    val caches = Seq.fill(2)(Module(new CoherentLineCache(bytes = 4096, lines = 2, params = params)))
    val agents = Seq(io.hart0, io.hart1)
    for (i <- 0 until 2) {
        val agent = agents(i)
        val cache = caches(i)
        cache.io.flushRequest := false.B
        cache.io.upstream.request.valid := agent.request.valid
        cache.io.upstream.request.bits := agent.request.bits
        agent.request.ready := cache.io.upstream.request.ready
        agent.response.valid := cache.io.upstream.response.valid
        agent.response.bits := cache.io.upstream.response.bits
        cache.io.upstream.response.ready := agent.response.ready
        cache.io.downstream.request.ready := false.B
        cache.io.downstream.response.valid := false.B
        cache.io.downstream.response.bits := 0.U.asTypeOf(new DataResponse)
        assert(!cache.io.downstream.request.valid, "two-hart test only issues cacheable ordinary traffic")
        home.io.drainRequest := false.B
    home.io.clients(i) <> cache.io.tl
    }
    io.probe0 := caches(0).io.tl.b.fire
    io.probe1 := caches(1).io.tl.b.fire
    io.dirtyProbe0 := caches(0).io.tl.c.fire && caches(0).io.tl.c.bits.opcode === TLOpcode.ProbeAckData
    io.dirtyProbe1 := caches(1).io.tl.c.fire && caches(1).io.tl.c.bits.opcode === TLOpcode.ProbeAckData
    io.releaseData0 := caches(0).io.tl.c.fire && caches(0).io.tl.c.bits.opcode === TLOpcode.ReleaseData
    io.releaseData1 := caches(1).io.tl.c.fire && caches(1).io.tl.c.bits.opcode === TLOpcode.ReleaseData
    val uncached = io.uncached
    home.io.upstream.request.valid := uncached.request.valid
    home.io.upstream.request.bits := uncached.request.bits
    uncached.request.ready := home.io.upstream.request.ready
    uncached.response.valid := home.io.upstream.response.valid
    uncached.response.bits := home.io.upstream.response.bits
    home.io.upstream.response.ready := uncached.response.ready
    home.io.upstreamRequestCpu := false.B

    val bridge = Module(new OrderedTileLinkBridge(orderedWrites = true,
        orderedMixedAccesses = true, allowWriteErrors = true))
    bridge.io.data <> home.io.downstream
    val arbiter = Module(new TwoMasterTileLinkArbiter(params))
    arbiter.io.masters(0) <> bridge.io.tl
    arbiter.io.masters(1) <> home.io.line
    io.burstWriteBeat := home.io.line.a.fire &&
        home.io.line.a.bits.opcode === TLOpcode.PutFullData && home.io.line.a.bits.size === 6.U
    val manager = Module(new TileLinkDataRamAdapter(params = params.copy(sourceBits = 4),
        burstEnabled = true, burstBytes = 4096))
    manager.io.tl <> arbiter.io.manager
    val ram = Module(new SynchronousDataRam(bytes = 4096))
    ram.io.port <> manager.io.memory
}

object TwoHartCoherentGsimMain extends App {
    val output = Paths.get(args.head)
    Files.createDirectories(output)
    ChiselStage.emitCHIRRTLFile(new TwoHartCoherentGsim, Array("--target-dir", output.toString))
}
