package ooo.hometagram

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.core.ooo.{CoherentLineHome, CoherentLineHomeModule, DataPort, NonBlockingCoherentLineHome, MixedCoherentLineHome, CacheTagConfig, CoherentWriteDispatch}

/** Tag-storage fixture reuses the protocol-only driver without exposing directory internals.
  * The aperture crosses 4 GiB so compact tags retain and test bit 32.
  */
class HomeMshrGsim(entries: Int, compact: Boolean, lines: Int, mixed: Boolean) extends Module {
    private val base = BigInt("ffff0000", 16)
    private val bytes = BigInt(0x20000)
    require(Set(2, 4).contains(entries))
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3,
        sinkBits = math.max(1, log2Ceil(entries)))
    val io = IO(new Bundle {
        val dispatchOffer_0 = Input(Bool())
        val dispatchOffer_1 = Input(Bool())
        val dispatchSeed_0 = Input(UInt(64.W))
        val dispatchSeed_1 = Input(UInt(64.W))
        val dispatchReady = Input(Bool())
        val dispatchAccepted_0 = Output(Bool())
        val dispatchAccepted_1 = Output(Bool())
        val dispatchValid = Output(Bool())
        val dispatchTag = Output(UInt(2.W))
        val dispatchAddress = Output(UInt(64.W))
        val dispatchWords_0 = Output(UInt(64.W))
        val dispatchWords_1 = Output(UInt(64.W))
        val dispatchWords_2 = Output(UInt(64.W))
        val dispatchWords_3 = Output(UInt(64.W))
        val dispatchWords_4 = Output(UInt(64.W))
        val dispatchWords_5 = Output(UInt(64.W))
        val dispatchWords_6 = Output(UInt(64.W))
        val dispatchWords_7 = Output(UInt(64.W))
        val upstream = Flipped(new DataPort)
        val upstreamRequestCpu = Input(Bool())
        val downstream = new DataPort
        val client = Flipped(new TLBundle(params))
        val line = new TLBundle(params)
    })
    val home: CoherentLineHomeModule = if (mixed)
        Module(new MixedCoherentLineHome(params, base = base, bytes = bytes,
            trackedLines = lines, trackedWays = 2, acquireEntries = entries,
            writebackEntries = 2, mixedReadWrite = true, tagConfig = CacheTagConfig(compact)))
    else Module(new NonBlockingCoherentLineHome(params, base = base, bytes = bytes,
        trackedLines = lines, trackedWays = 2, acquireEntries = entries, tagConfig = CacheTagConfig(compact)))
    // Same production helper, independently driven to force spill/full/stall
    // cases that the home's four-slot writer may absorb in ordinary traffic.
    val dispatch = Module(new CoherentWriteDispatch(64, 2))
    val offers = Seq(io.dispatchOffer_0, io.dispatchOffer_1)
    val seeds = Seq(io.dispatchSeed_0, io.dispatchSeed_1)
    val accepted = Seq(io.dispatchAccepted_0, io.dispatchAccepted_1)
    for (i <- 0 until 2) {
        dispatch.io.in(i).valid := offers(i)
        dispatch.io.in(i).bits.address := Cat(seeds(i)(57, 0), 0.U(6.W))
        dispatch.io.in(i).bits.tag := i.U
        dispatch.io.in(i).bits.data := Cat((0 until 8).reverse.map(j => seeds(i) + j.U(64.W)))
        accepted(i) := dispatch.io.in(i).fire
    }
    dispatch.io.out.ready := io.dispatchReady
    io.dispatchValid := dispatch.io.out.valid
    io.dispatchTag := dispatch.io.out.bits.tag
    io.dispatchAddress := dispatch.io.out.bits.address
    val dispatchWords = dispatch.io.out.bits.data.asTypeOf(Vec(8, UInt(64.W)))
    for ((port, i) <- Seq(io.dispatchWords_0, io.dispatchWords_1, io.dispatchWords_2, io.dispatchWords_3, io.dispatchWords_4, io.dispatchWords_5, io.dispatchWords_6, io.dispatchWords_7).zipWithIndex) { port := dispatchWords(i) }
    home.io.drainRequest := false.B
    home.io.upstream <> io.upstream
    home.io.upstreamRequestCpu := io.upstreamRequestCpu
    io.downstream <> home.io.downstream
    home.io.clients(0) <> io.client
    io.line <> home.io.line
}

object HomeTagRamGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new HomeMshrGsim(args(1).toInt, args(2) == "1", args(3).toInt,
        args(4) == "1"), Array("--target-dir", args.head))
}
