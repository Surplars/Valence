package soc.ip.memory

import chisel3._
import chisel3.util._

/** Shared I1/A1 native memory wire format, independent of either CPU pipeline.
  * Ordinary data uses physical 64-bit beat lanes; atomic operands/results are
  * right-justified. Virtual authorization metadata is consumed inside the tile.
  * A CPU/fabric boundary must never forward virtualized requests to a manager.
  */
class NativeMemoryRequest(returnHandleBits: Int = 0) extends Bundle {
    require(returnHandleBits >= 0)
    val returnHandle = if (returnHandleBits > 0) Some(UInt(returnHandleBits.W)) else None
    val atomic = Bool()
    val atomicOp = UInt(5.W)
    val address = UInt(64.W)
    val write = Bool()
    val size = UInt(2.W)
    val data = UInt(64.W)
    val mask = UInt(8.W)
    val virtualized = Bool()
    val precheckedLoad = Bool()
    val translationEpoch = UInt(32.W)
    val prefetchNextAllowed = Bool()
    val uncached = Bool()
}

class NativeMemoryResponse(returnHandleBits: Int = 0) extends Bundle {
    require(returnHandleBits >= 0)
    val returnHandle = if (returnHandleBits > 0) Some(UInt(returnHandleBits.W)) else None
    val data = UInt(64.W)
    val error = Bool()
    val pageFault = Bool()
}

/** Every accepted request owns exactly one real completion. Untagged ports
  * preserve response order. Optional return handles transport an existing CPU
  * reservation; they do not authorize early write acknowledgements or reorder
  * reads/IO. These wires are single-domain; asynchronous use needs full FIFOs.
  */
class NativeMemoryPort(returnHandleBits: Int = 0) extends Bundle {
    val request = Decoupled(new NativeMemoryRequest(returnHandleBits))
    val response = Flipped(Decoupled(new NativeMemoryResponse(returnHandleBits)))
}
