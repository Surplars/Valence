package inorder

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.core.inorder._
import soc.ip.tilelink._

class I1HomeGrantMetadata(p: TLParams) extends Bundle {
    val source = UInt(p.sourceBits.W); val sink = UInt(p.sinkBits.W)
    val denied = Bool(); val corrupt = Bool()
}

/** Real Home; externally retained two-slot memory responses, no payload model
  * or expected-value logic in the DUT. Scalar packing for the pinned GSIM.
  */
class I1HomeReadPairFixture extends Module {
    val p = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val a0 = Flipped(Decoupled(new TLBundleA(p))); val a1 = Flipped(Decoupled(new TLBundleA(p)))
        val e0 = Flipped(Decoupled(new TLBundleE(p))); val e1 = Flipped(Decoupled(new TLBundleE(p)))
        val read = Decoupled(new LineFillRequest(64, 8))
        val responseValid = Input(Bool()); val responseReady = Output(Bool())
        val responseTag = Input(UInt(8.W)); val responseError = Input(Bool())
        val word0 = Input(UInt(64.W)); val word1 = Input(UInt(64.W))
        val word2 = Input(UInt(64.W)); val word3 = Input(UInt(64.W))
        val word4 = Input(UInt(64.W)); val word5 = Input(UInt(64.W))
        val word6 = Input(UInt(64.W)); val word7 = Input(UInt(64.W))
        val g0 = Decoupled(new I1HomeGrantMetadata(p)); val g1 = Decoupled(new I1HomeGrantMetadata(p))
        val inspect = Input(Bool())
        val result0 = Output(UInt(64.W)); val result1 = Output(UInt(64.W))
        val result2 = Output(UInt(64.W)); val result3 = Output(UInt(64.W))
        val result4 = Output(UInt(64.W)); val result5 = Output(UInt(64.W))
        val result6 = Output(UInt(64.W)); val result7 = Output(UInt(64.W))
        val probe = Output(Bool()); val drained = Output(Bool())
    })
    val home = Module(new I1CoherentLineHome(p, bytes = 16384, nClients = 2,
        trackedLines = 64, trackedWays = 4, parallelQualification = true,
        ordinaryWritePipeline = true, lineDispatchFlow = true, wholeLineRead = true,
        internalLineGrant = true, writebackOverlap = true, readOverlap = true))
    for ((c, i) <- home.io.clients.zipWithIndex) {
        c.a <> Seq(io.a0, io.a1)(i); c.e <> Seq(io.e0, io.e1)(i)
        val g = Seq(io.g0, io.g1)(i)
        val actual = home.io.lineGrants.get(i)
        g.valid := actual.valid; actual.ready := g.ready
        g.bits.source := actual.bits.source; g.bits.sink := actual.bits.sink
        g.bits.denied := actual.bits.denied; g.bits.corrupt := actual.bits.corrupt
        c.b.ready := false.B; c.c.valid := false.B; c.c.bits := 0.U.asTypeOf(c.c.bits)
        c.d.ready := true.B
    }
    io.probe := home.io.clients.map(_.b.valid).reduce(_ || _)
    io.read <> home.io.lineRead.get.request
    val response = home.io.lineRead.get.response
    response.valid := io.responseValid; io.responseReady := response.ready
    response.bits.tag := io.responseTag; response.bits.error := io.responseError
    response.bits.data := Cat(Seq(io.word7, io.word6, io.word5, io.word4,
        io.word3, io.word2, io.word1, io.word0))
    val inspected = Mux(io.inspect, home.io.lineGrants.get(1).bits.data, home.io.lineGrants.get(0).bits.data)
    for ((r, i) <- Seq(io.result0, io.result1, io.result2, io.result3,
        io.result4, io.result5, io.result6, io.result7).zipWithIndex) {
        r := inspected(64 * i + 63, 64 * i)
    }
    home.io.upstream.request.valid := false.B
    home.io.upstream.request.bits := 0.U.asTypeOf(home.io.upstream.request.bits)
    home.io.upstream.response.ready := true.B
    home.io.upstreamRequestCpu := false.B; home.io.drainRequest := false.B
    home.io.downstream.request.ready := false.B
    home.io.downstream.response.valid := false.B
    home.io.downstream.response.bits := 0.U.asTypeOf(home.io.downstream.response.bits)
    home.io.line.a.ready := false.B
    home.io.line.b.valid := false.B; home.io.line.b.bits := 0.U.asTypeOf(home.io.line.b.bits)
    home.io.line.c.ready := false.B; home.io.line.e.ready := false.B
    home.io.line.d.valid := false.B; home.io.line.d.bits := 0.U.asTypeOf(home.io.line.d.bits)
    io.drained := home.io.drainDone
}

object I1HomeReadPairMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1HomeReadPairFixture, Array("--target-dir", args.head))
}
