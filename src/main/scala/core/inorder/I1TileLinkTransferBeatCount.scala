// Independent I1 bus adapter, copied from TileLinkTransferBeatCount.scala; no CPU/OoO state/control.
package soc.core.inorder

import chisel3._
import chisel3.util._
import soc.bus.tilelink.TLParams

/** Transaction ownership counts the TL size domain, independently of AXI buffer capacity. */
private[inorder] object I1TileLinkTransferBeatCount {
    def width(params: TLParams): Int = {
        require(params.sizeBits >= 3 && params.sizeBits <= 6, "bridge supports TL size fields of 3..6 bits")
        (1 << params.sizeBits) - 3
    }
    def apply(size: UInt, params: TLParams): UInt = {
        val bits = width(params)
        MuxLookup(size, 1.U(bits.W))((4 until (1 << params.sizeBits)).map { n =>
            n.U -> (BigInt(1) << (n - 3)).U(bits.W)
        })
    }
}
