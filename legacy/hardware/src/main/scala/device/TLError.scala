package soc.device

import chisel3._
import soc.bus.tilelink._

class TLError(params: TLParams) extends Module {
    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(params))
    })
    TLBundle.tieoffSlaveCoherence(io.tl)

    val respValid = RegInit(false.B)
    val respOpcode = RegInit(TLOpcode.AccessAck)
    val respParam = RegInit(0.U(3.W))
    val respSize = RegInit(0.U(params.sizeBits.W))
    val respSource = RegInit(0.U(params.sourceBits.W))

    io.tl.a.ready := !respValid

    when(io.tl.a.fire) {
        respValid := true.B
        respOpcode := TLOpcode.responseOpcodeForA(io.tl.a.bits.opcode)
        respParam := TLOpcode.responseParamForA(io.tl.a.bits.opcode, io.tl.a.bits.param)
        respSize := io.tl.a.bits.size
        respSource := io.tl.a.bits.source
    }

    io.tl.d.valid := respValid
    io.tl.d.bits.opcode := respOpcode
    io.tl.d.bits.param := respParam
    io.tl.d.bits.size := respSize
    io.tl.d.bits.source := respSource
    io.tl.d.bits.sink := 0.U
    io.tl.d.bits.denied := true.B
    io.tl.d.bits.data := 0.U
    io.tl.d.bits.corrupt := false.B

    when(io.tl.d.fire) {
        respValid := false.B
    }
}
