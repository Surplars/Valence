package soc.core

import chisel3._
import chisel3.util._
import soc.bus.tilelink.TLParams
import soc.memory.{CacheReq, CacheResp}

class DcachePtwArbiter(val params: TLParams) extends Module {
    val io = IO(new Bundle {
        val ifetchPtwReq = Flipped(Decoupled(new CacheReq(params.addrWidth, params.dataWidth)))
        val ifetchPtwResp = Decoupled(new CacheResp(params.dataWidth))
        val lsuReq = Flipped(Decoupled(new CacheReq(params.addrWidth, params.dataWidth)))
        val lsuResp = Decoupled(new CacheResp(params.dataWidth))
        val cacheReq = Decoupled(new CacheReq(params.addrWidth, params.dataWidth))
        val cacheResp = Flipped(Decoupled(new CacheResp(params.dataWidth)))
        val maintPending = Input(Bool())
        val respPending = Output(Bool())
        val respOwnerPtw = Output(Bool())
        val cacheReqFire = Output(Bool())
        val cacheRespFire = Output(Bool())
    })

    val respPending = RegInit(false.B)
    val respOwnerPtw = RegInit(false.B)
    val acceptNewReq = !io.maintPending && !respPending
    val ifetchSelected = acceptNewReq && io.ifetchPtwReq.valid && !io.lsuReq.valid

    io.cacheReq.valid := acceptNewReq && Mux(ifetchSelected, io.ifetchPtwReq.valid, io.lsuReq.valid)
    io.cacheReq.bits := Mux(ifetchSelected, io.ifetchPtwReq.bits, io.lsuReq.bits)
    io.ifetchPtwReq.ready := ifetchSelected && io.cacheReq.ready
    io.lsuReq.ready := acceptNewReq && !ifetchSelected && io.cacheReq.ready

    val cacheReqFire = io.cacheReq.fire
    val respOwner = Mux(cacheReqFire && !respPending, ifetchSelected, respOwnerPtw)

    io.ifetchPtwResp.valid := io.cacheResp.valid && !io.maintPending && respOwner
    io.ifetchPtwResp.bits := io.cacheResp.bits
    io.lsuResp.valid := io.cacheResp.valid && !io.maintPending && !respOwner
    io.lsuResp.bits := io.cacheResp.bits
    io.cacheResp.ready := Mux(io.maintPending, true.B, Mux(respOwner, io.ifetchPtwResp.ready, io.lsuResp.ready))

    val cacheRespFire = io.cacheResp.fire
    when(cacheReqFire && !cacheRespFire) {
        respPending := true.B
        respOwnerPtw := ifetchSelected
    }.elsewhen(cacheRespFire) {
        respPending := false.B
    }

    io.respPending := respPending
    io.respOwnerPtw := respOwnerPtw
    io.cacheReqFire := cacheReqFire
    io.cacheRespFire := cacheRespFire
}
