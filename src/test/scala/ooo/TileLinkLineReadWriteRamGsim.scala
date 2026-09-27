package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.TLParams
import soc.core.ooo.{SynchronousDataRam, TileLinkDataRamAdapter}
import soc.ip.tilelink.TileLinkLineTransfer

class TileLinkLineReadWriteRamGsim extends Module {
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val writeRequest = Flipped(Decoupled(new Bundle {
            val address = UInt(64.W)
            val tag = UInt(8.W)
        }))
        val writeWord0 = Input(UInt(64.W))
        val writeWord1 = Input(UInt(64.W))
        val writeWord2 = Input(UInt(64.W))
        val writeWord3 = Input(UInt(64.W))
        val writeWord4 = Input(UInt(64.W))
        val writeWord5 = Input(UInt(64.W))
        val writeWord6 = Input(UInt(64.W))
        val writeWord7 = Input(UInt(64.W))
        val writeResponse = Decoupled(new Bundle {
            val tag = UInt(8.W)
            val error = Bool()
        })
        val readRequest = Flipped(Decoupled(new Bundle {
            val address = UInt(64.W)
            val tag = UInt(8.W)
        }))
        val readResponse = Decoupled(new Bundle {
            val tag = UInt(8.W)
            val error = Bool()
        })
        val readWord0 = Output(UInt(64.W))
        val readWord1 = Output(UInt(64.W))
        val readWord2 = Output(UInt(64.W))
        val readWord3 = Output(UInt(64.W))
        val readWord4 = Output(UInt(64.W))
        val readWord5 = Output(UInt(64.W))
        val readWord6 = Output(UInt(64.W))
        val readWord7 = Output(UInt(64.W))
    })
    val transfer = Module(new TileLinkLineTransfer(params))
    val adapter = Module(new TileLinkDataRamAdapter(params = params.copy(sourceBits = params.sourceBits + 1),
        burstEnabled = true))
    val ram = Module(new SynchronousDataRam())

    transfer.io.writeRequest.valid := io.writeRequest.valid
    transfer.io.writeRequest.bits.address := io.writeRequest.bits.address
    transfer.io.writeRequest.bits.tag := io.writeRequest.bits.tag
    transfer.io.writeRequest.bits.data := Cat(io.writeWord7, io.writeWord6, io.writeWord5, io.writeWord4,
        io.writeWord3, io.writeWord2, io.writeWord1, io.writeWord0)
    io.writeRequest.ready := transfer.io.writeRequest.ready
    io.writeResponse <> transfer.io.writeResponse
    transfer.io.readRequest <> io.readRequest
    io.readResponse.valid := transfer.io.readResponse.valid
    io.readResponse.bits.tag := transfer.io.readResponse.bits.tag
    io.readResponse.bits.error := transfer.io.readResponse.bits.error
    transfer.io.readResponse.ready := io.readResponse.ready
    io.readWord0 := transfer.io.readResponse.bits.data(63, 0)
    io.readWord1 := transfer.io.readResponse.bits.data(127, 64)
    io.readWord2 := transfer.io.readResponse.bits.data(191, 128)
    io.readWord3 := transfer.io.readResponse.bits.data(255, 192)
    io.readWord4 := transfer.io.readResponse.bits.data(319, 256)
    io.readWord5 := transfer.io.readResponse.bits.data(383, 320)
    io.readWord6 := transfer.io.readResponse.bits.data(447, 384)
    io.readWord7 := transfer.io.readResponse.bits.data(511, 448)
    transfer.io.tl <> adapter.io.tl
    adapter.io.memory <> ram.io.port
}

object TileLinkLineReadWriteRamGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TileLinkLineReadWriteRamGsim, Array("--target-dir", args.head))
}
