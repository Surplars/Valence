package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundleA, TLBundleD, TLBundleE, TLParams}
import soc.ip.tilelink.{LineAcquireRequest, TileLinkLineAcquireEngine}

/** Same original Acquire owner/buffer, two selectable private data transports. */
class WholeLineGrantGsim(wide: Boolean) extends Module {
    private val p = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 2)
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new LineAcquireRequest(64, 8)))
        val a = Decoupled(new TLBundleA(p))
        val d = Flipped(Decoupled(new TLBundleD(p)))
        val e = Decoupled(new TLBundleE(p))
        val fullValid = Input(Bool())
        val fullReady = Output(Bool())
        val fullSource = Input(UInt(3.W))
        val fullSink = Input(UInt(2.W))
        val fullCap = Input(UInt(2.W))
        val fullDenied = Input(Bool())
        val fullCorrupt = Input(Bool())
        val inputWords = Input(new PostedBoardWords)
        val outputWords = Output(new PostedBoardWords)
        val resultValid = Output(Bool())
        val resultReady = Input(Bool())
        val tag = Output(UInt(8.W))
        val error = Output(Bool())
        val cap = Output(UInt(2.W))
    })
    val engine = Module(new TileLinkLineAcquireEngine(p, entries = 2, internalLineGrant = wide))
    engine.io.request <> io.request
    io.a <> engine.io.a
    engine.io.d <> io.d
    io.e <> engine.io.e
    io.fullReady := false.B
    engine.io.lineGrant.foreach { g =>
        g.valid := io.fullValid
        io.fullReady := g.ready
        g.bits.source := io.fullSource
        g.bits.sink := io.fullSink
        g.bits.cap := io.fullCap
        g.bits.denied := io.fullDenied
        g.bits.corrupt := io.fullCorrupt
        g.bits.data := Cat(io.inputWords.words.reverse)
    }
    io.resultValid := engine.io.response.valid
    engine.io.response.ready := io.resultReady
    io.tag := engine.io.response.bits.tag
    io.error := engine.io.response.bits.error
    io.cap := engine.io.response.bits.cap
    for ((word, i) <- io.outputWords.words.zipWithIndex)
        word := engine.io.response.bits.data(64 * i + 63, 64 * i)
}

object WholeLineGrantGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)))
    ChiselStage.emitCHIRRTLFile(new WholeLineGrantGsim(args(1) == "1"), Array("--target-dir", args(0)))
}
