package ip

import _root_.circt.stage.ChiselStage
import soc.ip.dma.EthernetPacketDma
import chisel3._
import chisel3.util._
import soc.core.ooo._
import soc.ip.bus.RegisterPort
import soc.bus.tilelink.TLParams

/** Uses the same atomic/coherence home as production; external byte oracle is C++.
  * No CPU instruction simulator or DUT RAM is used as the correctness oracle.
  */
class EthernetDmaCoherenceGsim(cacheLines: Int = 4, postedTxSlots: Int = 0) extends Module {
    private val base = BigInt("80200000", 16)
    private val testRamBytes = math.max(8192, cacheLines * 128)
    val io = IO(new Bundle {
        val control = Flipped(new RegisterPort)
        val memory = new RegisterPort
        val cpu = Flipped(new DataPort)
        val txData = Decoupled(new soc.ip.dma.EthernetAxisWord)
        val txControl = Decoupled(new soc.ip.dma.EthernetAxisWord)
        val rxData = Flipped(Decoupled(new soc.ip.dma.EthernetAxisWord))
        val rxStatus = Flipped(Decoupled(new soc.ip.dma.EthernetAxisWord))
        val irq = Output(Bool())
        val active = Output(Bool())
    })
    val dma = Module(new EthernetPacketDma(ramBytes = testRamBytes, postedTxSlots = postedTxSlots))
    io.control <> dma.io.control
    io.txData <> dma.io.txData
    io.txControl <> dma.io.txControl
    dma.io.rxData <> io.rxData
    dma.io.rxStatus <> io.rxStatus
    io.irq := dma.io.irq
    io.active := dma.io.active
    val cache = Module(new CoherentLineCache(base = base, bytes = testRamBytes, lines = cacheLines, ways = 2))
    val shared = Module(new AtomicDataMemory(base = base, bytes = testRamBytes, registerResponseOwners = true))
    val home = Module(new CoherentLineHome(base = base, bytes = testRamBytes, trackedLines = cacheLines, trackedWays = 2))
    val bridge = Module(new OrderedTileLinkBridge(allowWriteErrors = true, allowPartialWrites = true))
    val arbiter = Module(new soc.ip.tilelink.TwoMasterTileLinkArbiter(
        TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)))
    val manager = Module(new TileLinkDataRamAdapter(
        params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4),
        burstEnabled = true, burstBase = base, burstBytes = testRamBytes))
    cache.io.upstream <> io.cpu
    cache.io.flushRequest := false.B
    shared.io.cpu <> cache.io.downstream
    shared.io.clearReservation := false.B
    val lanes = Module(new DmaRegisterDataAdapter)
    lanes.io.registers <> dma.io.memory
    shared.io.dma <> lanes.io.data
    home.io.drainRequest := false.B
    home.io.upstream <> shared.io.memory
    home.io.upstreamRequestCpu := shared.io.memoryRequestCpu
    home.io.clients(0) <> cache.io.tl
    bridge.io.data <> home.io.downstream
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

object EthernetDmaCoherenceGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new EthernetDmaCoherenceGsim(args.lift(1).map(_.toInt).getOrElse(4),
        args.lift(2).map(_.toInt).getOrElse(0)), Array("--target-dir", args.head))
}

object EthernetPacketDmaGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new EthernetPacketDma(ramBytes = args.lift(3).map(BigInt(_)).getOrElse(BigInt(8192)),
        postedRxSlots = args.lift(1).map(_.toInt).getOrElse(4),
        memoryCredits = args.lift(2).map(_.toInt).getOrElse(4),
        postedTxSlots = args.lift(4).map(_.toInt).getOrElse(0)), Array("--target-dir", args.head))
}

object EthernetPacketDmaRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(new EthernetPacketDma(), Array("--target-dir", args.head),
        Array("--split-verilog", "-disable-all-randomization", "-strip-debug-info"))
}
