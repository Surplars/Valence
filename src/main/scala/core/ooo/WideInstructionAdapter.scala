package soc.core.ooo

import chisel3._
import chisel3.util._

/** Uses two ordered 8-byte transactions where a 16-byte instruction port meets a narrow ROM or TL bridge. */
class WideInstructionAdapter extends Module {
    val io = IO(new Bundle {
        val wide = Flipped(new InstructionPort(4))
        val narrow = new InstructionPort(2)
    })
    private val Seq(idle, sendLow, waitLow, sendHigh, waitHigh, reply) = Enum(6)
    private val state = RegInit(idle)
    private val address = Reg(UInt(64.W))
    private val mask = Reg(UInt(4.W))
    private val lowData = Reg(UInt(64.W))
    private val highData = Reg(UInt(64.W))
    private val lowError = Reg(UInt(2.W))
    private val highError = Reg(UInt(2.W))
    private val lowPage = Reg(UInt(2.W))
    private val highPage = Reg(UInt(2.W))

    val completingHigh = state === waitHigh && io.narrow.response.valid
    io.wide.response.valid := state === reply || completingHigh
    io.wide.response.bits := Cat(Mux(state === reply, highData, io.narrow.response.bits), lowData)
    io.wide.responseError := Cat(Mux(state === reply, highError, io.narrow.responseError), lowError)
    io.wide.responsePageFault := Cat(Mux(state === reply, highPage, io.narrow.responsePageFault), lowPage)
    io.wide.request.ready := state === idle || io.wide.response.fire
    val completingLow = state === waitLow && io.narrow.response.valid
    val requestHigh = state === sendHigh || completingLow
    io.narrow.request.valid := state === sendLow || requestHigh
    io.narrow.request.bits := address + Mux(requestHigh, 8.U, 0.U)
    io.narrow.requestMask := Mux(requestHigh, mask(3, 2), mask(1, 0))
    when(io.narrow.request.fire && state === sendLow) { state := waitLow }
    when(io.narrow.request.fire && state === sendHigh) { state := waitHigh }
    io.narrow.response.ready := state === waitLow || state === waitHigh
    when(io.narrow.response.fire) {
        when(state === waitLow) {
            lowData := io.narrow.response.bits
            lowError := io.narrow.responseError
            lowPage := io.narrow.responsePageFault
            state := Mux(io.narrow.request.fire, waitHigh, sendHigh)
        }.otherwise {
            highData := io.narrow.response.bits
            highError := io.narrow.responseError
            highPage := io.narrow.responsePageFault
            state := Mux(io.wide.response.ready, idle, reply)
        }
    }
    when(io.wide.response.fire && state === reply) { state := idle }
    when(io.wide.request.fire) {
        address := io.wide.request.bits
        mask := io.wide.requestMask
        state := sendLow
    }
}
