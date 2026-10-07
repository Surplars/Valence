package soc.memory.cache

import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.memory.{CacheReq, CacheResp}

class UncachedTileLinkBridge(val params: TLParams) extends Module with HasCacheCoreIO {
    val io = IO(new CacheCoreIO(params))
    TLBundle.tieoffMasterCoherence(io.bus)

    val reqValid = RegInit(false.B)
    val reqReg = Reg(new CacheReq(params.addrWidth, params.dataWidth))
    val respValid = RegInit(false.B)
    val respData = RegInit(0.U(params.dataWidth.W))
    val respErr = RegInit(false.B)
    val maintenanceReq = io.cpu.req.bits.fence || io.cpu.req.bits.fencei

    io.cpu.req.ready := !reqValid && !respValid
    io.invalidate.ready := true.B
    when(io.cpu.req.fire) {
        when(maintenanceReq) {
            respValid := true.B
            respData := 0.U
            respErr := false.B
        }.otherwise {
            reqValid := true.B
            reqReg := io.cpu.req.bits
        }
    }

    io.bus.a.valid := reqValid
    io.bus.a.bits.opcode := Mux(reqReg.cmd === CacheCmd.Read, TLOpcode.Get, TLOpcode.PutPartialData)
    io.bus.a.bits.param := 0.U
    io.bus.a.bits.size := reqReg.size
    io.bus.a.bits.source := 0.U
    io.bus.a.bits.address := reqReg.addr
    io.bus.a.bits.mask := reqReg.mask
    io.bus.a.bits.data := reqReg.wdata
    io.bus.a.bits.corrupt := false.B

    when(io.bus.a.fire) {
        reqValid := false.B
    }

    io.bus.d.ready := !respValid
    when(io.bus.d.fire) {
        respValid := true.B
        respData := io.bus.d.bits.data
        respErr := io.bus.d.bits.denied
    }

    io.cpu.resp.valid := respValid
    io.cpu.resp.bits.rdata := respData
    io.cpu.resp.bits.err := respErr
    when(io.cpu.resp.fire) {
        respValid := false.B
    }
}
