package inorder

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.ip.tilelink._

/** Actual production Acquire engine, scalar packing only for pinned GSIM. */
class I1LineGrantTransportFixture extends Module {
    val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new LineAcquireRequest(64, 8)))
        val a = Decoupled(new TLBundleA(params))
        val e = Decoupled(new TLBundleE(params))
        val grantValid = Input(Bool()); val grantReady = Output(Bool())
        val source = Input(UInt(3.W)); val sink = Input(UInt(params.sinkBits.W))
        val cap = Input(UInt(2.W)); val denied = Input(Bool()); val corrupt = Input(Bool())
        val word0 = Input(UInt(64.W)); val word1 = Input(UInt(64.W))
        val word2 = Input(UInt(64.W)); val word3 = Input(UInt(64.W))
        val word4 = Input(UInt(64.W)); val word5 = Input(UInt(64.W))
        val word6 = Input(UInt(64.W)); val word7 = Input(UInt(64.W))
        val responseReady = Input(Bool()); val responseValid = Output(Bool())
        val responseError = Output(Bool()); val responseTag = Output(UInt(8.W))
        val result0 = Output(UInt(64.W)); val result1 = Output(UInt(64.W))
        val result2 = Output(UInt(64.W)); val result3 = Output(UInt(64.W))
        val result4 = Output(UInt(64.W)); val result5 = Output(UInt(64.W))
        val result6 = Output(UInt(64.W)); val result7 = Output(UInt(64.W))
    })
    val engine = Module(new TileLinkLineAcquireEngine(params, entries = 2, internalLineGrant = true))
    engine.io.request <> io.request; io.a <> engine.io.a; io.e <> engine.io.e
    engine.io.d.valid := false.B; engine.io.d.bits := 0.U.asTypeOf(engine.io.d.bits)
    val grant = engine.io.lineGrant.get
    grant.valid := io.grantValid; io.grantReady := grant.ready
    grant.bits.source := io.source; grant.bits.sink := io.sink; grant.bits.cap := io.cap
    grant.bits.denied := io.denied; grant.bits.corrupt := io.corrupt
    grant.bits.data := Cat(Seq(io.word7, io.word6, io.word5, io.word4,
        io.word3, io.word2, io.word1, io.word0))
    engine.io.response.ready := io.responseReady
    io.responseValid := engine.io.response.valid; io.responseError := engine.io.response.bits.error
    io.responseTag := engine.io.response.bits.tag
    for ((result, i) <- Seq(io.result0, io.result1, io.result2, io.result3,
        io.result4, io.result5, io.result6, io.result7).zipWithIndex) {
        result := engine.io.response.bits.data(64 * i + 63, 64 * i)
    }
}

object I1LineGrantTransportMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1LineGrantTransportFixture, Array("--target-dir", args.head))
}
