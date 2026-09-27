package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.ip.tilelink.{TileLinkLineTransfer, TileLinkLineWriteEngine}

class TileLinkLineWriteGsim extends Module {
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new Bundle {
            val address = UInt(64.W)
            val tag = UInt(8.W)
        }))
        val word0 = Input(UInt(64.W))
        val word1 = Input(UInt(64.W))
        val word2 = Input(UInt(64.W))
        val word3 = Input(UInt(64.W))
        val word4 = Input(UInt(64.W))
        val word5 = Input(UInt(64.W))
        val word6 = Input(UInt(64.W))
        val word7 = Input(UInt(64.W))
        val response = Decoupled(new Bundle {
            val tag = UInt(8.W)
            val error = Bool()
        })
        val tl = new TLBundle(params)
    })
    val write = Module(new TileLinkLineWriteEngine(params, entries = 4))
    write.io.request.valid := io.request.valid
    write.io.request.bits.address := io.request.bits.address
    write.io.request.bits.tag := io.request.bits.tag
    write.io.request.bits.data := Cat(io.word7, io.word6, io.word5, io.word4,
        io.word3, io.word2, io.word1, io.word0)
    io.request.ready := write.io.request.ready
    io.response <> write.io.response
    io.tl <> write.io.tl
}

object TileLinkLineWriteGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TileLinkLineWriteGsim, Array("--target-dir", args.head))
}

object TileLinkLineWriteRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new TileLinkLineWriteEngine(TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)),
        Array("--target-dir", args.head)
    )
}

object TileLinkLineTransferRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new TileLinkLineTransfer(TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)),
        Array("--target-dir", args.head)
    )
}
