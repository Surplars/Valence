package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundle, TLOpcode, TLParams}
import soc.core.ooo.{InstructionRom, TileLinkInstructionRomAdapter}

/** The board ROM manager also serves CPU byte/halfword literal-data loads. */
class BoardRomGsim(bufferedReplies: Boolean = false, creditTest: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val write = Input(Bool())
        val index = Input(UInt(15.W))
        val data = Input(UInt(32.W))
        val requestValid = Input(Bool())
        val requestReady = Output(Bool())
        val address = Input(UInt(64.W))
        val size = Input(UInt(3.W))
        val mask = Input(UInt(8.W))
        val responseReady = Input(Bool())
        val responseValid = Output(Bool())
        val responseData = Output(UInt(64.W))
        val responseError = Output(Bool())
        val source = if (creditTest) Some(Input(UInt(3.W))) else None
        val responseSource = if (creditTest) Some(Output(UInt(3.W))) else None
        val responseSize = if (creditTest) Some(Output(UInt(3.W))) else None
    })
    val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val adapter = Module(new TileLinkInstructionRomAdapter(32768, params = params, bufferedReplies = bufferedReplies))
    val rom = Module(new InstructionRom(32768, BigInt("80000000", 16), programmable = true))
    adapter.io.rom <> rom.io.fetch
    rom.io.write.get.valid := io.write
    rom.io.write.get.bits.index := io.index
    rom.io.write.get.bits.data := io.data
    adapter.io.tl.a.valid := io.requestValid
    adapter.io.tl.a.bits := 0.U.asTypeOf(adapter.io.tl.a.bits)
    adapter.io.tl.a.bits.opcode := TLOpcode.Get
    adapter.io.tl.a.bits.source := io.source.getOrElse(0.U)
    adapter.io.tl.a.bits.address := io.address
    adapter.io.tl.a.bits.size := io.size
    adapter.io.tl.a.bits.mask := io.mask
    io.requestReady := adapter.io.tl.a.ready
    adapter.io.tl.d.ready := io.responseReady
    io.responseValid := adapter.io.tl.d.valid
    io.responseData := adapter.io.tl.d.bits.data
    io.responseError := adapter.io.tl.d.bits.denied
    io.responseSource.foreach(_ := adapter.io.tl.d.bits.source)
    io.responseSize.foreach(_ := adapter.io.tl.d.bits.size)
    adapter.io.tl.b.ready := true.B
    adapter.io.tl.c.valid := false.B
    adapter.io.tl.c.bits := 0.U.asTypeOf(adapter.io.tl.c.bits)
    adapter.io.tl.e.valid := false.B
    adapter.io.tl.e.bits := 0.U.asTypeOf(adapter.io.tl.e.bits)
}

object BoardRomGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new BoardRomGsim(args.drop(1).contains("buffered-replies"),
        args.drop(1).contains("credit-test")), Array("--target-dir", args.head))
}
