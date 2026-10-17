package soc.core.ooo

import chisel3._
import chisel3.util._

/** B/H/W/D naturally aligned accesses occupy one 64-bit beat. The caller
  * authorizes the stored beat/mask only after address-known + safe-RAM checks.
  * Nonaligned loads stay conservative until the head LSU reports their fault.
  * Zero latency/II=1; no XLEN end-address carry or ordered magnitude compare.
  */
object AlignedMemoryDisjoint {
    def aligned(address: UInt, size: UInt): Bool = {
        val mask = MuxLookup(size, 7.U(3.W))(Seq(0.U -> 0.U, 1.U -> 1.U, 2.U -> 3.U))
        (address(2, 0) & mask) === 0.U
    }
    def lanes(address: UInt, size: UInt): UInt = {
        val mask = MuxLookup(size, 255.U(8.W))(Seq(0.U -> 1.U, 1.U -> 3.U, 2.U -> 15.U))
        (mask << address(2, 0))(7, 0)
    }
    def withLanes(loadAddress: UInt, loadAligned: Bool, loadLanes: UInt,
        storeBeat: UInt, storeLanes: UInt): Bool = {
        val differentBeat = VecInit((0 until 61 by 6).map { low =>
            val high = math.min(low + 5, 60)
            loadAddress(high + 3, low + 3) =/= storeBeat(high, low)
        }).asUInt.orR
        loadAligned && (differentBeat || !(loadLanes & storeLanes).orR)
    }
    def apply(loadAddress: UInt, loadSize: UInt, storeAddress: UInt, storeSize: UInt): Bool =
        aligned(storeAddress, storeSize) && withLanes(loadAddress, aligned(loadAddress, loadSize),
            lanes(loadAddress, loadSize), storeAddress(63, 3), lanes(storeAddress, storeSize))
}
