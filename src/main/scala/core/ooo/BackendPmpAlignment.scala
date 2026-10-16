package soc.core.ooo

import chisel3._
import chisel3.util._

/** Checker-only address bridge. The original address remains the LSU/trap authority.
  * For a two-bit size this clears only the natural-alignment bits. Aligned requests
  * are unchanged; misaligned PMP decisions may differ only behind the caller's
  * existing misalignment guards. Never use this address to issue memory traffic.
  */
object BackendPmpAlignment {
    def checkerAddress(address: UInt, size: UInt): UInt = {
        require(address.getWidth == 64 && size.getWidth == 2,
            "backend aligned PMP requires the actual RV64 address and two-bit size")
        val mask = MuxLookup(size, 7.U(3.W))(Seq(0.U -> 0.U, 1.U -> 1.U, 2.U -> 3.U))
        Cat(address(63, 3), address(2, 0) & ~mask)
    }
}
