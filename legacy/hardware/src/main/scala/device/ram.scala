package soc.device

import chisel3._
import chisel3.util._

import soc.system.MMIO

class SramIO(AW: Int, dataBytes: Int) extends MMIO(AW, dataBytes)

class Sram(AW: Int, DW: Int, depthWords: Int, dataBytes: Int = 4) extends Module {
    require(isPow2(depthWords), "depth must be power of two")
    require(DW % 8 == 0, "DW must be byte-aligned")

    val io = IO(new SramIO(AW, dataBytes))

    val mem = SyncReadMem(depthWords, Vec(dataBytes, UInt(8.W)))

    when(io.write) {
        mem.write(io.addr, io.dataIn, io.mask)
    }

    io.dataOut := mem.read(io.addr, io.read)
}
