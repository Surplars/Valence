package soc.memory

import chisel3._
import soc.bus.tilelink.TLParams

class MmioMaster(params: TLParams) extends Bundle {
    val req_valid = Output(Bool())
    val req_addr  = Output(UInt(params.addrWidth.W))
    val req_cmd   = Output(UInt(3.W))                      // Get/Put
    val req_data  = Output(UInt(params.dataWidth.W))       // 仅 Put 需要
    val req_mask  = Output(UInt((params.dataWidth / 8).W)) // 仅 Put 需要
    val req_size  = Output(UInt(params.sizeBits.W))        // 访问大小 (2^size 字节)
    val req_ready = Input(Bool())

    val resp_valid  = Input(Bool())
    val resp_data   = Input(UInt(params.dataWidth.W))
    val resp_cmd    = Input(UInt(3.W))
    val resp_source = Input(UInt(params.sourceBits.W))
    val resp_err    = Input(Bool())
}

import cache.CacheCmd

class CacheReq(val addrWidth: Int, val dataWidth: Int) extends Bundle {
    val addr      = UInt(addrWidth.W)
    val vaddr     = UInt(addrWidth.W)
    val cmd       = CacheCmd.Type()
    val wdata     = UInt(dataWidth.W)
    val mask      = UInt((dataWidth / 8).W)
    val size      = UInt(3.W)
    val signed    = Bool()
    val fence     = Bool()
    val fencei    = Bool()
    val atomic    = Bool()
    val cacheable = Bool()
    val device    = Bool()
}

class CacheResp(val dataWidth: Int) extends Bundle {
    val rdata = UInt(dataWidth.W)
    val err   = Bool()
}
