package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.core.ooo.TileLinkAxi4Bridge
import soc.ip.axi.Axi4MemoryPort
import soc.ip.tilelink.{RegisteredTileLinkBoundary, TwoMasterTileLinkArbiter, TwoMasterTwoBankTileLinkCrossbar}

/** The board's non-coherent backing-fabric topology, with independent traffic drivers.
  *
  * DMA/direct and coherent-home backing requests meet at the nested arbiter;
  * instruction traffic is the other crossbar master. All modules are the real
  * production implementations. The C++ oracle supplies disjoint, already
  * authorized TL-UL requests. It does not instantiate the CPU/cache/home, and
  * must not be called a simultaneous coherent CPU/DMA board benchmark: home
  * maintenance deliberately drains upstream activity before direct access.
  *
  * Capacity is unchanged: four DDR transactions, at most two writes, 16 beats.
  * Registered boundaries add one A and one D cycle and target II=1. Independent
  * AXI R/W and per-master D stalls test ownership and forward progress; physical
  * DDR timing, CDC, FPGA timing and application IPC remain outside this wrapper.
  */
class BusFabricThroughputGsim extends Module {
    private val leafParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    private val fabricParams = leafParams.copy(sourceBits = 4)
    private val managerParams = fabricParams.copy(sourceBits = 5)
    private val romBase = BigInt("80000000", 16)
    private val romBytes = BigInt(1) << 21
    private val ramBase = romBase + romBytes
    private val ramBytes = BigInt(1) << 31
    val io = IO(new Bundle {
        val fetch = Flipped(new TLBundle(fabricParams))
        val home = Flipped(new TLBundle(leafParams))
        val dma = Flipped(new TLBundle(leafParams))
        val rom = new TLBundle(managerParams)
        val axi = new Axi4MemoryPort(32, 4)
    })

    private val dataArbiter = Module(new TwoMasterTileLinkArbiter(leafParams,
        rawResponseMetadata = true, rawRequestMetadata = true))
    private val dataBoundary = Module(new RegisteredTileLinkBoundary(fabricParams))
    private val fetchBoundary = Module(new RegisteredTileLinkBoundary(fabricParams))
    private val crossbar = Module(new TwoMasterTwoBankTileLinkCrossbar(fabricParams,
        base = romBase, bankBytes = romBytes, secondBankBytes = ramBytes,
        prefixAddressDecode = true, rawResponseMetadata = true, rawRequestMetadata = true))
    private val ddr = Module(new TileLinkAxi4Bridge(tlParams = managerParams,
        axiAddressWidth = 32, axiIdWidth = 4, maxBurstBeats = 16,
        axiAddressBase = ramBase, axiWindowBytes = ramBytes,
        maxOutstanding = 4, maxOutstandingWrites = 2, unorderedResponses = true))

    dataArbiter.io.masters(0) <> io.dma
    dataArbiter.io.masters(1) <> io.home
    dataBoundary.io.upstream <> dataArbiter.io.manager
    fetchBoundary.io.upstream <> io.fetch
    crossbar.io.masters(0) <> dataBoundary.io.downstream
    crossbar.io.masters(1) <> fetchBoundary.io.downstream
    io.rom <> crossbar.io.banks(0)
    ddr.io.tl <> crossbar.io.banks(1)
    io.axi <> ddr.io.axi
}

object BusFabricThroughputGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new BusFabricThroughputGsim, Array("--target-dir", args.head))
}
