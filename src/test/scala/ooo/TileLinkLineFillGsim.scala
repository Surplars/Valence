package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.ip.tilelink.{LineFillRequest, TileLinkLineFillEngine}

class TileLinkLineFillGsim extends Module {
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new LineFillRequest(64, 8)))
        val response = Decoupled(new Bundle {
            val tag = UInt(8.W)
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
        val tl = new TLBundle(params)
    })
    val fill = Module(new TileLinkLineFillEngine(params, entries = 4))
    fill.io.request <> io.request
    io.tl <> fill.io.tl
    io.response.valid := fill.io.response.valid
    io.response.bits.tag := fill.io.response.bits.tag
    io.response.bits.error := fill.io.response.bits.error
    fill.io.response.ready := io.response.ready
    io.word0 := fill.io.response.bits.data(63, 0)
    io.word1 := fill.io.response.bits.data(127, 64)
    io.word2 := fill.io.response.bits.data(191, 128)
    io.word3 := fill.io.response.bits.data(255, 192)
    io.word4 := fill.io.response.bits.data(319, 256)
    io.word5 := fill.io.response.bits.data(383, 320)
    io.word6 := fill.io.response.bits.data(447, 384)
    io.word7 := fill.io.response.bits.data(511, 448)
}

object TileLinkLineFillGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TileLinkLineFillGsim, Array("--target-dir", args.head))
}

object TileLinkLineFillRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new TileLinkLineFillEngine(TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)),
        Array("--target-dir", args.head)
    )
}
