package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._
import soc.bus.tilelink.TLParams
import soc.ip.bus.RegisterPort

/** Production FIFO/home path; external byte-addressed memory is the only oracle.
  * holdProbe models legal B-channel transport backpressure, NOT a private-state hook.
  */
class NetworkProbeGsim(ways: Int, lines: Int = 4, productionMetadata: Boolean = false) extends Module {
    private val base = BigInt("80200000", 16)
    val io = IO(new Bundle {
        val cpu = Flipped(new DataPort)
        val dma = Flipped(new DataPort)
        val memory = new RegisterPort
        val holdProbe = Input(Bool())
        val bypassPending = Output(Bool())
    })
    val cache = Module(new CoherentLineCache(base = base, bytes = 8192, lines = lines, ways = ways))
    val shared = Module(new AtomicDataMemory(base = base, bytes = 8192, registerResponseOwners = true))
    val buffer = Module(new DataRequestBuffer(registerHead = true))
    val home = Module(new CoherentLineHome(base = base, bytes = 8192, trackedLines = lines, trackedWays = ways,
        rawResponseMetadata = productionMetadata, parallelQualification = productionMetadata))
    val bridge = Module(new OrderedTileLinkBridge(allowWriteErrors = true, allowPartialWrites = true))
    val arbiter = Module(new soc.ip.tilelink.TwoMasterTileLinkArbiter(
        TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)))
    val manager = Module(new TileLinkDataRamAdapter(
        params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4),
        burstEnabled = true, burstBase = base, burstBytes = 8192))
    cache.io.upstream <> io.cpu
    cache.io.flushRequest := false.B
    shared.io.cpu <> cache.io.downstream
    shared.io.dma <> io.dma
    shared.io.clearReservation := false.B
    buffer.io.upstream <> shared.io.memory
    buffer.io.requestCpu := shared.io.memoryRequestCpu
    home.io.drainRequest := false.B
    home.io.upstream <> buffer.io.downstream
    home.io.upstreamRequestCpu := buffer.io.downstreamRequestCpu
    home.io.clients(0) <> cache.io.tl
    cache.io.tl.b.valid := home.io.clients(0).b.valid && !io.holdProbe
    home.io.clients(0).b.ready := cache.io.tl.b.ready && !io.holdProbe
    io.bypassPending := cache.io.downstream.request.fire
    bridge.io.data <> home.io.downstream
    // Public port contract: a downstream TL producer may already have locked
    // this offered request. Neither valid nor payload may be withdrawn/changed.
    val homeStalled = RegNext(home.io.downstream.request.valid && !home.io.downstream.request.ready, false.B)
    val homeHeld = RegEnable(home.io.downstream.request.bits,
        home.io.downstream.request.valid && !home.io.downstream.request.ready)
    when(homeStalled) {
        assert(home.io.downstream.request.valid, "Home withdrew a stalled downstream request")
        assert(home.io.downstream.request.bits.asUInt === homeHeld.asUInt,
            "Home changed a stalled downstream request payload")
    }
    arbiter.io.masters(0) <> bridge.io.tl
    arbiter.io.masters(1) <> home.io.line
    manager.io.tl <> arbiter.io.manager
    io.memory.request.valid := manager.io.memory.request.valid
    io.memory.request.bits.address := manager.io.memory.request.bits.address
    io.memory.request.bits.write := manager.io.memory.request.bits.write
    io.memory.request.bits.data := manager.io.memory.request.bits.data >>
        Cat(manager.io.memory.request.bits.address(2, 0), 0.U(3.W))
    io.memory.request.bits.size := manager.io.memory.request.bits.size
    io.memory.request.bits.byteEnable := manager.io.memory.request.bits.mask >>
        manager.io.memory.request.bits.address(2, 0)
    manager.io.memory.request.ready := io.memory.request.ready
    manager.io.memory.response.valid := io.memory.response.valid
    manager.io.memory.response.bits.data := io.memory.response.bits.data
    manager.io.memory.response.bits.error := io.memory.response.bits.error
    manager.io.memory.response.bits.pageFault := false.B
    io.memory.response.ready := manager.io.memory.response.ready
}

object NetworkProbeGsimMain extends App {
    val lines = if (args.length > 2) args(2).toInt else 4
    val productionMetadata = args.length > 3 && args(3) == "production"
    ChiselStage.emitCHIRRTLFile(new NetworkProbeGsim(args(1).toInt, lines, productionMetadata),
        Array("--target-dir", args.head))
}
