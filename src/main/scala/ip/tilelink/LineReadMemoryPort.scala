package soc.ip.tilelink

import chisel3._
import chisel3.util._

/** A tagged 64-byte ordinary-memory read, after coherence/permission resolution.
  * One accepted request owns its full tag until the whole-line response fires.
  * A late backing-memory error applies to the entire line; error data is zero.
  * This is not an early-completion or bypass-coherence interface.
  */
class LineReadMemoryPort(addressBits: Int = 64, tagBits: Int = 8) extends Bundle {
    val request = Decoupled(new LineFillRequest(addressBits, tagBits))
    val response = Flipped(Decoupled(new LineFillResponse(tagBits)))
}
