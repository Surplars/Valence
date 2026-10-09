package soc.ip.dma

import chisel3._
import chisel3.util._

/** Naturally aligned 64-byte RAM transactions; no partial lines or MMIO.
  * Accepted tags remain unique until their matching response handshakes; replies
  * may return out of order. Offered payloads stay stable under backpressure.
  * A write response follows its backing acknowledgement. There is no hot abort:
  * clients drain every accepted/irrevocable offer before descriptor reuse/reset.
  */
class DmaLineRequest(tagBits: Int = 1) extends Bundle {
    val tag = UInt(tagBits.W)
    val address = UInt(64.W)
    val data = UInt(512.W)
    val write = Bool()
}
class DmaLineResponse(tagBits: Int = 1) extends Bundle {
    val tag = UInt(tagBits.W)
    val data = UInt(512.W)
    val error = Bool()
}
class DmaLinePort(entries: Int = 1) extends Bundle {
    require(Set(1, 2, 4).contains(entries))
    private val tagBits = math.max(1, log2Ceil(entries))
    val request = Decoupled(new DmaLineRequest(tagBits))
    val response = Flipped(Decoupled(new DmaLineResponse(tagBits)))
}
