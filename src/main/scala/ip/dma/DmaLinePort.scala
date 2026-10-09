package soc.ip.dma

import chisel3._
import chisel3.util._

/** One naturally aligned 64-byte RAM transaction. No partial lines or MMIO.
  * A write response means the backing write acknowledgement was consumed.
  * Request and response payloads remain stable under backpressure.
  */
class DmaLineRequest extends Bundle {
    val address = UInt(64.W)
    val data = UInt(512.W)
    val write = Bool()
}
class DmaLineResponse extends Bundle {
    val data = UInt(512.W)
    val error = Bool()
}
class DmaLinePort extends Bundle {
    val request = Decoupled(new DmaLineRequest)
    val response = Flipped(Decoupled(new DmaLineResponse))
}
