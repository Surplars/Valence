package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundleB, TLBundleC, TLParams}
import soc.ip.tilelink.{LineProbeRequest, TileLinkLineProbeEngine}

class TileLinkLineProbeGsim extends Module {
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new LineProbeRequest(64, 8)))
        val response = Decoupled(new Bundle {
            val tag = UInt(8.W)
            val hasData = Bool()
            val corrupt = Bool()
        })
        val word0 = Output(UInt(64.W))
        val word1 = Output(UInt(64.W))
        val word2 = Output(UInt(64.W))
        val word3 = Output(UInt(64.W))
        val word4 = Output(UInt(64.W))
        val word5 = Output(UInt(64.W))
        val word6 = Output(UInt(64.W))
        val word7 = Output(UInt(64.W))
        val probe = Decoupled(new TLBundleB(params))
        val ack = Flipped(Decoupled(new TLBundleC(params)))
    })
    val engine = Module(new TileLinkLineProbeEngine(params, entries = 4))
    engine.io.request <> io.request
    io.probe <> engine.io.probe
    engine.io.ack <> io.ack
    io.response.valid := engine.io.response.valid
    io.response.bits.tag := engine.io.response.bits.tag
    io.response.bits.hasData := engine.io.response.bits.hasData
    io.response.bits.corrupt := engine.io.response.bits.corrupt
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

object TileLinkLineProbeGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TileLinkLineProbeGsim, Array("--target-dir", args.head))
}

object TileLinkLineProbeRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new TileLinkLineProbeEngine(TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)),
        Array("--target-dir", args.head)
    )
}
