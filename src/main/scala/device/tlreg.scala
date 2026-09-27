package soc.device

import chisel3._
import chisel3.util._

import soc.bus.tilelink._

class TLRegister(params: TLParams) extends Module {
    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(params))
    })
    TLBundle.tieoffSlaveCoherence(io.tl)

    private val beatBytes = params.dataWidth / 8
    private val reqReady = Wire(Bool())

    val regBytes = RegInit(VecInit(Seq.fill(beatBytes)(0.U(8.W))))
    val respValid = RegInit(false.B)
    val respOpcode = RegInit(TLOpcode.AccessAck)
    val respParam = RegInit(0.U(3.W))
    val respSize = RegInit(0.U(params.sizeBits.W))
    val respSource = RegInit(0.U(params.sourceBits.W))
    val respData = RegInit(0.U(params.dataWidth.W))
    val respDenied = RegInit(false.B)

    io.tl.a.ready := reqReady
    reqReady := !respValid

    when(io.tl.a.fire) {
        val isWrite = io.tl.a.bits.opcode === TLOpcode.PutFullData || io.tl.a.bits.opcode === TLOpcode.PutPartialData
        val isRead = io.tl.a.bits.opcode === TLOpcode.Get
        val isLegal = isRead || isWrite
        val writeBytes = VecInit(Seq.tabulate(beatBytes)(i => io.tl.a.bits.data(8 * i + 7, 8 * i)))

        when(isWrite) {
            for (i <- 0 until beatBytes) {
                when(io.tl.a.bits.mask(i)) {
                    regBytes(i) := writeBytes(i)
                }
            }
        }

        respValid := true.B
        respOpcode := TLOpcode.responseOpcodeForA(io.tl.a.bits.opcode)
        respParam := TLOpcode.responseParamForA(io.tl.a.bits.opcode, io.tl.a.bits.param)
        respSize := io.tl.a.bits.size
        respSource := io.tl.a.bits.source
        respData := Mux(isRead, regBytes.asUInt, 0.U)
        respDenied := !isLegal
    }

    io.tl.d.valid := respValid
    io.tl.d.bits.opcode := respOpcode
    io.tl.d.bits.param := respParam
    io.tl.d.bits.size := respSize
    io.tl.d.bits.source := respSource
    io.tl.d.bits.sink := 0.U
    io.tl.d.bits.denied := respDenied
    io.tl.d.bits.data := respData
    io.tl.d.bits.corrupt := false.B

    when(io.tl.d.fire) {
        respValid := false.B
    }
}
