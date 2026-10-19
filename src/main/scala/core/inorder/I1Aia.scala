package soc.core.inorder

import chisel3._
import chisel3.util._
import soc.ip.bus.RegisterResponse
import soc.ip.interrupt.ImsicCsrRequest

/** One irrevocable, serial WB owner. No speculative CSR requests may enter this port.
  * The responder must report an illegal access without applying its side effect.
  */
class I1AiaCsrPort extends Bundle {
    val request = Decoupled(new ImsicCsrRequest)
    val response = Flipped(Decoupled(new RegisterResponse))
}

object I1Aia {
    def indirect(address: UInt): Bool = address === "h351".U || address === "h151".U ||
        address === "h35c".U || address === "h15c".U
}
