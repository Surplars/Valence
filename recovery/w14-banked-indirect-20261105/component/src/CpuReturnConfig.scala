package soc.core.ooo

import chisel3._
import chisel3.util._

/** CPU-local reservations, unrelated to ROB generations or TileLink/AXI IDs.
  * A slot's handle cannot be reused while its previous actual reply is outstanding.
  */
case class CpuReturnConfig(memoryEntries: Int, storeBufferEntries: Int, fpEnabled: Boolean) {
    require(memoryEntries > 0 && storeBufferEntries > 0)
    val handleCount: Int = memoryEntries + storeBufferEntries + (if (fpEnabled) 1 else 0)
    val handleBits: Int = math.max(1, log2Ceil(handleCount))
    val tableEntries: Int = 1 << handleBits
    val fpHandle: Int = memoryEntries + storeBufferEntries
    def integer(handle: UInt): Bool = handle < memoryEntries.U
    def store(handle: UInt): Bool = handle >= memoryEntries.U && handle < fpHandle.U
    def legal(handle: UInt): Bool = handle < handleCount.U
    def storeHandle(index: UInt): UInt = (memoryEntries.U(handleBits.W) + index)(handleBits - 1, 0)
}

