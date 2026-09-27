package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.TLParams
import soc.core.ooo.{SynchronousDataRam, TileLinkDataRamAdapter}
import soc.ip.tilelink.{LineFillRequest, TileLinkLineFillEngine}

class TileLinkLineFillRamGsim extends Module {
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
        val programValid = Input(Bool())
        val programIndex = Input(UInt(9.W))
        val programData = Input(UInt(64.W))
    })
    val fill = Module(new TileLinkLineFillEngine(params, entries = 4))
    val adapter = Module(new TileLinkDataRamAdapter(params = params, burstEnabled = true))
    val ram = Module(new SynchronousDataRam(programmable = true))
    fill.io.request <> io.request
    fill.io.tl <> adapter.io.tl
    adapter.io.memory <> ram.io.port
    ram.io.program.get.valid := io.programValid
    ram.io.program.get.bits.index := io.programIndex
    ram.io.program.get.bits.data := io.programData
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

object TileLinkLineFillRamGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TileLinkLineFillRamGsim, Array("--target-dir", args.head))
}
