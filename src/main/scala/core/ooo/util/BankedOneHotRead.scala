package soc.core.ooo

import chisel3._
import chisel3.util._

/** Bounded two-level read from registers: local eight-word banks followed by
  * one-hot bank selection. Zero state/latency, II=1, exact for every index.
  * The index must encode exactly the power-of-two depth, never a compact PRF
  * with invalid holes. No wide tag/data mux is serialized after a priority.
  */
private[ooo] object BankedOneHotRead {
    def apply[T <: Data](values: Vec[T], index: UInt): T = {
        require(values.length >= 8 && isPow2(values.length))
        require(index.getWidth == log2Ceil(values.length))
        val localSelect = UIntToOH(index(2, 0), 8)
        val banks = values.toSeq.grouped(8).map(bank => Mux1H(localSelect, bank)).toSeq
        if (banks.length == 1) banks.head
        else Mux1H(UIntToOH(index(index.getWidth - 1, 3), banks.length), banks)
    }
}
