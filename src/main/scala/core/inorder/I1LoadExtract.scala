package soc.core.inorder

import chisel3._
import chisel3.util._

/** Parallel byte selection and sign extraction. No owner, register or extra load cycle. */
object I1LoadExtract {
    def apply(data: UInt, byteOffset: UInt, funct3: UInt, direct: Bool,
        fallback: UInt, selected: Bool): (UInt, UInt) = {
        val width = data.getWidth
        require(width == 32 || width == 64)
        val bytes = width / 8
        // SC returns a complete status word rather than an address-selected lane.
        val offset = Mux(direct, 0.U, byteOffset)
        val size = Mux(direct, log2Ceil(bytes).U(2.W), funct3(1, 0))
        val lanes = UIntToOH(offset, bytes).asBools
        val shifted = I1ExecuteDatapath.operand(lanes,
            (0 until bytes).map(i => (data >> (8 * i)).pad(width)))
        // Merge the existing ALU/non-load result in the byte reduction. The
        // return data does not cross a second XLEN load/non-load mux afterwards.
        val resultBytes = (0 until bytes).map { out =>
            val threshold = log2Ceil(out + 1)
            val normal = lanes.map(_ && selected && size >= threshold.U)
            val normalData = (0 until bytes).map { first =>
                if (first + out < bytes) data(8 * (first + out) + 7, 8 * (first + out)) else 0.U(8.W)
            }
            val sign = if (threshold == 0) Seq.empty[Bool] else (0 until bytes).map { last =>
                val formats = (0 until threshold).filter(s => (1 << s) <= last + 1).map { s =>
                    size === s.U && offset === (last + 1 - (1 << s)).U
                }
                selected && !funct3(2) && formats.reduce(_ || _)
            }
            val signData = if (threshold == 0) Seq.empty[UInt] else
                (0 until bytes).map(last => Fill(8, data(8 * last + 7)))
            I1ExecuteDatapath.operand(normal ++ sign :+ !selected,
                normalData ++ signData :+ fallback(8 * out + 7, 8 * out))
        }
        (shifted, Cat(resultBytes.reverse))
    }
}
