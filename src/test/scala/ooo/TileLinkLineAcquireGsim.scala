package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundleA, TLBundleD, TLBundleE, TLParams}
import soc.ip.tilelink.{LineAcquireRequest, TileLinkLineAcquireEngine}

class TileLinkLineAcquireGsim extends Module {
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 2)
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new LineAcquireRequest(64, 8)))
        val response = Decoupled(new Bundle {
            val tag = UInt(8.W)
            val hasData = Bool()
            val cap = UInt(2.W)
            val error = Bool()
        })
        val word0 = Output(UInt(64.W))
        val word1 = Output(UInt(64.W))
        val word2 = Output(UInt(64.W))
        val word3 = Output(UInt(64.W))
        val word4 = Output(UInt(64.W))
        val word5 = Output(UInt(64.W))
        val word6 = Output(UInt(64.W))
        val word7 = Output(UInt(64.W))
        val a = Decoupled(new TLBundleA(params))
        val d = Flipped(Decoupled(new TLBundleD(params)))
        val e = Decoupled(new TLBundleE(params))
    })
    val engine = Module(new TileLinkLineAcquireEngine(params, entries = 4))
    engine.io.request <> io.request
    io.a <> engine.io.a
    engine.io.d <> io.d
    io.e <> engine.io.e
    io.response.valid := engine.io.response.valid
    io.response.bits.tag := engine.io.response.bits.tag
    io.response.bits.hasData := engine.io.response.bits.hasData
    io.response.bits.cap := engine.io.response.bits.cap
    io.response.bits.error := engine.io.response.bits.error
    engine.io.response.ready := io.response.ready
    io.word0 := engine.io.response.bits.data(63, 0)
    io.word1 := engine.io.response.bits.data(127, 64)
    io.word2 := engine.io.response.bits.data(191, 128)
    io.word3 := engine.io.response.bits.data(255, 192)
    io.word4 := engine.io.response.bits.data(319, 256)
    io.word5 := engine.io.response.bits.data(383, 320)
    io.word6 := engine.io.response.bits.data(447, 384)
    io.word7 := engine.io.response.bits.data(511, 448)
}

object TileLinkLineAcquireGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TileLinkLineAcquireGsim, Array("--target-dir", args.head))
}

object TileLinkLineAcquireRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new TileLinkLineAcquireEngine(TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 2)),
        Array("--target-dir", args.head)
    )
}
