package soc.core.inorder

import chisel3._
import chisel3.util._

/** Bounded FPGA reductions. No extra owner, storage, or arithmetic latency. */
object I1TimingMath {
    /** Constant power-of-two increment with independent short carry-select chunks.
      * Carry into each chunk is a reduction of ORIGINAL lower bits, never the
      * carry-out of the previous adder. BTB length selects only completed words.
      */
    def incrementPowerOfTwo(value: UInt, bit: Int, chunkBits: Int = 16): UInt = {
        val width = value.getWidth
        require(bit >= 0 && bit < width && chunkBits >= 4)
        val chunks = (0 until width by chunkBits).map { low =>
            val high = math.min(width - 1, low + chunkBits - 1)
            val part = value(high, low)
            if (high < bit) part
            else if (low <= bit) (part + (BigInt(1) << (bit - low)).U)(high - low, 0)
            else {
                val carry = value(low - 1, bit).andR
                Mux(carry, (part + 1.U)(high - low, 0), part)
            }
        }
        Cat(chunks.reverse)
    }

    def equal(left: UInt, right: UInt, groupBits: Int = 6): Bool = {
        require(groupBits >= 1 && groupBits <= 6)
        val width = math.max(left.getWidth, right.getWidth)
        val a = left.pad(width); val b = right.pad(width)
        VecInit((0 until width by groupBits).map { low =>
            val high = math.min(width - 1, low + groupBits - 1)
            !(a(high, low) ^ b(high, low)).orR
        }).asUInt.andR
    }

    def less(left: UInt, right: UInt): Bool = {
        val width = math.max(left.getWidth, right.getWidth)
        val a = left.pad(width); val b = right.pad(width)
        // Two NATIVE carry halves, not a software LUT-prefix comparator.
        // The low carry must not cross the entire 64-bit bypass/ALU cone.
        if (width > 32) {
            val upperA = a(width - 1, 32); val upperB = b(width - 1, 32)
            (upperA < upperB) || (equal(upperA, upperB) && a(31, 0) < b(31, 0))
        } else a < b
    }

    /** Native carry-select halves; same combinational result and owner edge. */
    def add(left: UInt, right: UInt, subtract: Bool = false.B, chunkBits: Int = 32): UInt = {
        require(left.getWidth == right.getWidth)
        require(Set(16, 32).contains(chunkBits))
        val width = left.getWidth
        val b = right ^ Fill(width, subtract)
        if (width > 32 && chunkBits == 16) {
            // Four independent native 16-bit sums with block lookahead.
            // No carry propagates across a whole 32-bit half after the EX
            // operand mux, and no incrementer follows a completed sum.
            val chunks = (0 until width by 16).map { low =>
                val high = math.min(width - 1, low + 15)
                val aPart = left(high, low); val bPart = b(high, low)
                val partWidth = high - low + 1
                val sum = aPart +& bPart
                val plusOne = ~((~aPart +& ~bPart)(partWidth - 1, 0))
                (sum(partWidth - 1, 0), plusOne, sum(partWidth), (aPart ^ bPart).andR)
            }
            val result = chunks.indices.map { i =>
                val carry = (0 until i).map { j =>
                    chunks(j)._3 && chunks.slice(j + 1, i).map(_._4).foldLeft(true.B)(_ && _)
                }.foldLeft(subtract && chunks.take(i).map(_._4).foldLeft(true.B)(_ && _))(_ || _)
                Mux(carry, chunks(i)._2, chunks(i)._1)
            }
            Cat(result.reverse)
        } else if (width > 32) {
            val low = left(31, 0) +& b(31, 0) + subtract
            val upperA = left(width - 1, 32); val upperB = b(width - 1, 32)
            val upperWidth = width - 32
            val noCarry = (upperA +& upperB)(upperWidth - 1, 0)
            // ~(~a + ~b) == a+b+1 modulo 2^N. This builds an independent
            // native carry path, not an incrementer AFTER the noCarry adder.
            val withCarry = ~((~upperA +& ~upperB)(upperWidth - 1, 0))
            Cat(Mux(low(32), withCarry, noCarry), low(31, 0))
        } else (left +& b + subtract)(width - 1, 0)
    }
}
