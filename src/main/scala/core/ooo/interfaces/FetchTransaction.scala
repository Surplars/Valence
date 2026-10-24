package soc.core.ooo

import chisel3._

/** Accepted fetch request and translation context, captured atomically.
  * Token is a transaction identity, not a branch or PMP epoch. The boundary
  * retains the existing architectural context-drain contract.
  */
class FetchTransactionCommand(val packetWords: Int = 2, val tokenBits: Int = 64) extends Bundle {
    require(Set(2, 4).contains(packetWords) && tokenBits > 0)
    val token = UInt(tokenBits.W)
    val virtualAddress = UInt(64.W)
    val requestMask = UInt(packetWords.W)
    val satp = UInt(64.W)
    val sum = Bool()
    val mxr = Bool()
    val privilege = UInt(2.W)
}

/** One terminal result for the original accepted token. Fault data is dead;
  * per-word fault vectors remain meaningful and stable with a held response.
  */
class FetchTransactionResult(val packetWords: Int = 2, val tokenBits: Int = 64) extends Bundle {
    require(Set(2, 4).contains(packetWords) && tokenBits > 0)
    val token = UInt(tokenBits.W)
    val data = UInt((32 * packetWords).W)
    val accessFaults = UInt(packetWords.W)
    val pageFaults = UInt(packetWords.W)
}
