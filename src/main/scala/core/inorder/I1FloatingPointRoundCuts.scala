/*============================================================================

This Chisel source file is part of a pre-release version of the HardFloat IEEE
Floating-Point Arithmetic Package, by John R. Hauser (with some contributions
from Yunsup Lee and Andrew Waterman, mainly concerning testing).

Copyright 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017 The Regents of the
University of California.  All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

 1. Redistributions of source code must retain the above copyright notice,
    this list of conditions, and the following disclaimer.

 2. Redistributions in binary form must reproduce the above copyright notice,
    this list of conditions, and the following disclaimer in the documentation
    and/or other materials provided with the distribution.

 3. Neither the name of the University nor the names of its contributors may
    be used to endorse or promote products derived from this software without
    specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE REGENTS AND CONTRIBUTORS "AS IS", AND ANY
EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE, ARE
DISCLAIMED.  IN NO EVENT SHALL THE REGENTS OR CONTRIBUTORS BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

=============================================================================*/

package soc.core.inorder

import chisel3._
import chisel3.util._
import hardfloat._
import hardfloat.consts._

/** Equal-format, options=0 HardFloat rounder, split before increment and packing.
  * Exact pinned RoundAnyRawFNToRecFN equations; no intermediate IEEE rounding.
  * Tininess is after rounding, as in the unchanged shared arithmetic parent.
  * One parent owner keeps raw input/rounding stable until the registered result.
  * Three added edges: mask -> increment -> recoded result; IEEE packing follows.
  */
class I1FloatingPointRoundCuts(e: Int, s: Int) extends Module {
    require(Set((8, 24), (11, 53)).contains((e, s)))
    val io = IO(new Bundle {
        val flush = Input(Bool())
        val start = Flipped(Valid(new I1FloatingPointRawResult(e, s)))
        val rounding = Input(UInt(3.W))
        val result = Valid(new Bundle {
            val value = UInt((e + s + 1).W)
            val flags = UInt(5.W)
            val nan = Bool()
        })
    })
    override def desiredName: String = "I1FloatingPointRoundCuts" + (if (e == 11) "D" else "S")
    val raw = io.start.bits
    val adjustedSig = raw.value.sig
    val exponent = raw.value.sExp
    val shiftDown = adjustedSig(s + 2)
    val nearEven = io.rounding === round_near_even
    val nearMax = io.rounding === round_near_maxMag
    val roundOdd = io.rounding === round_odd
    val magUp = (io.rounding === round_min && raw.value.sign) ||
        (io.rounding === round_max && !raw.value.sign)
    val nanExp = BigInt(7) << (e - 2)
    val infExp = BigInt(6) << (e - 2)
    val maxExp = infExp - 1
    val minNorm = (BigInt(1) << (e - 1)) + 2
    val minNonzero = minNorm - s + 1

    // Stage 1: subnormal/exponent-dependent rounding mask alone.
    val mask = RegEnable(Cat(lowMask(exponent(e, 0), minNorm - s - 1, minNorm) | shiftDown, 3.U(2.W)),
        io.start.valid && !io.flush)
    val maskValid = RegNext(io.start.valid && !io.flush, false.B)
    val shiftedMask = Cat(0.U(1.W), mask >> 1)
    val positionMask = ~shiftedMask & mask
    val positionBit = (adjustedSig & positionMask).orR
    val extra = (adjustedSig & shiftedMask).orR
    val any = positionBit || extra
    val increment = ((nearEven || nearMax) && positionBit) || (magUp && any)
    val incremented = (((adjustedSig | mask) >> 2) +& 1.U) &
        ~Mux(nearEven && positionBit && !extra, mask >> 1, 0.U((s + 2).W))
    val truncated = ((adjustedSig & ~mask) >> 2) |
        Mux(roundOdd && any, positionMask >> 1, 0.U)

    // Stage 2: significand carry before exponent/range checks and final encode.
    val rounded = RegEnable(Mux(increment, incremented, truncated), maskValid && !io.flush)
    val roundedPosition = RegEnable(positionBit, maskValid && !io.flush)
    val roundedAny = RegEnable(any, maskValid && !io.flush)
    val unboundedPosition = Mux(shiftDown, adjustedSig(2), adjustedSig(1))
    val unboundedAny = (shiftDown && adjustedSig(2)) || adjustedSig(1, 0).orR
    val unboundedIncrement = RegEnable(((nearEven || nearMax) && unboundedPosition) ||
        (magUp && unboundedAny), maskValid && !io.flush)
    val roundedValid = RegNext(maskValid && !io.flush, false.B)
    val roundedExponent = exponent +& (rounded >> s).asUInt.zext
    val fraction = Mux(shiftDown, rounded(s - 1, 1), rounded(s - 2, 0))
    val overflowCommon = (roundedExponent >> (e - 1)) >= 3.S
    val totalUnderflow = roundedExponent < minNonzero.S
    val carry = Mux(shiftDown, rounded(s + 1), rounded(s))
    val underflowCommon = totalUnderflow || (roundedAny && (exponent >> e) <= 0.S &&
        Mux(shiftDown, mask(3), mask(2)) &&
        !(!Mux(shiftDown, mask(4), mask(3)) && carry && roundedPosition && unboundedIncrement))
    val inexactCommon = totalUnderflow || roundedAny

    val isNaN = raw.invalid || raw.value.isNaN
    val specialInf = raw.infinite || raw.value.isInf
    val common = !isNaN && !specialInf && !raw.value.isZero
    val overflow = common && overflowCommon
    val underflow = common && underflowCommon
    val inexact = overflow || (common && inexactCommon)
    val overflowUp = nearEven || nearMax || magUp
    val pegMin = common && totalUnderflow && (magUp || roundOdd)
    val pegMax = overflow && !overflowUp
    val isInf = specialInf || (overflow && overflowUp)
    val sign = Mux(isNaN, false.B, raw.value.sign)
    val exp = (roundedExponent(e, 0) &
        ~Mux(raw.value.isZero || totalUnderflow, nanExp.U((e + 1).W), 0.U) &
        ~Mux(pegMin, ~minNonzero.U((e + 1).W), 0.U) &
        ~Mux(pegMax, (BigInt(1) << (e - 1)).U((e + 1).W), 0.U) &
        ~Mux(isInf, (BigInt(1) << (e - 2)).U((e + 1).W), 0.U)) |
        Mux(pegMin, minNonzero.U((e + 1).W), 0.U) |
        Mux(pegMax, maxExp.U((e + 1).W), 0.U) |
        Mux(isInf, infExp.U((e + 1).W), 0.U) |
        Mux(isNaN, nanExp.U((e + 1).W), 0.U)
    val fract = Mux(isNaN || raw.value.isZero || totalUnderflow,
        Mux(isNaN, (BigInt(1) << (s - 2)).U, 0.U), fraction) | Fill(s - 1, pegMax)

    // Stage 3: recoded result is stable before fNFromRecFN's denormal barrel.
    val recoded = RegEnable(Cat(sign, exp, fract), roundedValid && !io.flush)
    val flags = RegEnable(Cat(raw.invalid, raw.infinite, overflow, underflow, inexact),
        roundedValid && !io.flush)
    val nan = RegEnable(isNaN, roundedValid && !io.flush)
    val resultValid = RegNext(roundedValid && !io.flush, false.B)
    io.result.valid := resultValid && !io.flush
    io.result.bits.value := recoded
    io.result.bits.flags := flags
    io.result.bits.nan := nan
    when(io.flush) { maskValid := false.B; roundedValid := false.B; resultValid := false.B }
}
