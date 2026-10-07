package soc.system

import chisel3._

class MMIO(AW: Int, dataBytes: Int = 4) extends Bundle {
    val read    = Input(Bool())
    val write   = Input(Bool())
    val addr    = Input(UInt(AW.W))
    val mask    = Input(Vec(dataBytes, Bool()))
    val dataIn  = Input(Vec(dataBytes, UInt(8.W)))
    val dataOut = Output(Vec(dataBytes, UInt(8.W)))
}
