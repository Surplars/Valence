package soc.ip.axi

import chisel3._
import chisel3.util._

/** AXI4 64-bit memory channels, including INCR bursts. Optional USER/REGION stay in the platform wrapper. */
class Axi4Address(addressWidth: Int, idWidth: Int) extends Bundle {
    val id    = UInt(idWidth.W)
    val addr  = UInt(addressWidth.W)
    val len   = UInt(8.W)
    val size  = UInt(3.W)
    val burst = UInt(2.W)
    val lock  = Bool()
    val cache = UInt(4.W)
    val prot  = UInt(3.W)
    val qos   = UInt(4.W)
}

class Axi4WriteData extends Bundle {
    val data = UInt(64.W)
    val strb = UInt(8.W)
    val last = Bool()
}

class Axi4WriteResponse(idWidth: Int) extends Bundle {
    val id   = UInt(idWidth.W)
    val resp = UInt(2.W)
}

class Axi4ReadData(idWidth: Int) extends Bundle {
    val id   = UInt(idWidth.W)
    val data = UInt(64.W)
    val resp = UInt(2.W)
    val last = Bool()
}

class Axi4MemoryPort(addressWidth: Int = 64, idWidth: Int = 1) extends Bundle {
    require(addressWidth >= 32 && addressWidth <= 64)
    require(idWidth >= 1 && idWidth <= 8)
    val aw = Decoupled(new Axi4Address(addressWidth, idWidth))
    val w  = Decoupled(new Axi4WriteData)
    val b  = Flipped(Decoupled(new Axi4WriteResponse(idWidth)))
    val ar = Decoupled(new Axi4Address(addressWidth, idWidth))
    val r  = Flipped(Decoupled(new Axi4ReadData(idWidth)))
}
