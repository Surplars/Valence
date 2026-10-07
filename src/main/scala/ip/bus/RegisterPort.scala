package soc.ip.bus

import chisel3._
import chisel3.util._

/** Ordered, single-clock register transactions. Data/strobes are right-justified to the byte address. This is an
  * internal IP boundary, not an AXI or TileLink wire protocol. Adapters reject atomics.
  * Each instance belongs to one clock/reset domain: crossing requires a complete
  * request/response CDC adapter, never direct ready/valid wires or a normal Queue.
  * Planned board peripheral-domain contract: fpga/zu15eg/clock-domain-plan.md.
  */
class RegisterRequest extends Bundle {
    val address    = UInt(64.W)
    val write      = Bool()
    val size       = UInt(3.W)
    val data       = UInt(64.W)
    val byteEnable = UInt(8.W)
}
class RegisterResponse extends Bundle {
    val data  = UInt(64.W)
    val error = Bool()
}
class RegisterPort extends Bundle {
    val request  = Decoupled(new RegisterRequest)
    val response = Flipped(Decoupled(new RegisterResponse))
}
