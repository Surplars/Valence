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

/** Pinned RoundAnyRawFNToRecFN(11,53,8,24,sigMSBitAlwaysZero) equations.
  * Format/exponent/sticky preparation -> mask -> increment -> recoded result.
  * Exact signed exponent is retained, not truncated/saturated to binary32.
  * Tininess is after rounding; only one final IEEE rounding is performed.
  * The parent holds one owner; all four validity boundaries are flush-killed.
  */
class I1FloatingPointNarrowRoundCuts extends Module {
    val io = IO(new Bundle {
        val flush = Input(Bool())
        val start = Flipped(Valid(new RawFloat(11, 53)))
        val invalid = Input(Bool())
        val rounding = Input(UInt(3.W))
        val result = Valid(new Bundle {
            val value = UInt(33.W); val flags = UInt(5.W); val nan = Bool()
        })
    })
    val e = 8
    val s = 24
    val begin = io.start.valid && !io.flush
    val exponent = RegEnable(io.start.bits.sExp +&
        ((BigInt(1) << e) - (BigInt(1) << 11)).S, begin)
    val adjustedSig = RegEnable(Cat(io.start.bits.sig(53, 28), io.start.bits.sig(27, 0).orR), begin)
    val inputSign = RegEnable(io.start.bits.sign, begin)
    val inputZero = RegEnable(io.start.bits.isZero, begin)
    val inputInf = RegEnable(io.start.bits.isInf, begin)
    val inputNaN = RegEnable(io.start.bits.isNaN, begin)
    val invalid = RegEnable(io.invalid, begin)
    val rounding = RegEnable(io.rounding, begin)
    val prepared = RegNext(begin, false.B)
    val nearEven = rounding === round_near_even
    val nearMax = rounding === round_near_maxMag
    val odd = rounding === round_odd
    val magUp = (rounding === round_min && inputSign) || (rounding === round_max && !inputSign)
    val nanExp = BigInt(7) << (e - 2)
    val infExp = BigInt(6) << (e - 2)
    val maxExp = infExp - 1
    val minNorm = (BigInt(1) << (e - 1)) + 2
    val minNonzero = minNorm - s + 1
    // RawFloat from recoding has its extra significand MSB zero.
    val mask = RegEnable(Cat(lowMask(exponent(e, 0), minNorm - s - 1, minNorm), 3.U(2.W)),
        prepared && !io.flush)
    val maskValid = RegNext(prepared && !io.flush, false.B)
    val shiftedMask = Cat(0.U(1.W), mask >> 1)
    val positionMask = ~shiftedMask & mask
    val position = (adjustedSig & positionMask).orR
    val extra = (adjustedSig & shiftedMask).orR
    val any = position || extra
    val increment = ((nearEven || nearMax) && position) || (magUp && any)
    val incremented = (((adjustedSig | mask) >> 2) +& 1.U) &
        ~Mux(nearEven && position && !extra, mask >> 1, 0.U((s + 2).W))
    val truncated = ((adjustedSig & ~mask) >> 2) | Mux(odd && any, positionMask >> 1, 0.U)
    val rounded = RegEnable(Mux(increment, incremented, truncated), maskValid && !io.flush)
    val roundPosition = RegEnable(position, maskValid && !io.flush)
    val roundAny = RegEnable(any, maskValid && !io.flush)
    val unboundedIncrement = RegEnable(((nearEven || nearMax) && adjustedSig(1)) ||
        (magUp && adjustedSig(1, 0).orR), maskValid && !io.flush)
    val roundedValid = RegNext(maskValid && !io.flush, false.B)
    val roundedExponent = exponent +& (rounded >> s).asUInt.zext
    val overflowCommon = (roundedExponent >> (e - 1)) >= 3.S
    val totalUnderflow = roundedExponent < minNonzero.S
    val underflowCommon = totalUnderflow || (roundAny && (exponent >> e) <= 0.S && mask(2) &&
        !(!mask(3) && rounded(s) && roundPosition && unboundedIncrement))
    val isNaN = invalid || inputNaN
    val common = !isNaN && !inputInf && !inputZero
    val overflow = common && overflowCommon
    val underflow = common && underflowCommon
    val inexact = overflow || (common && (totalUnderflow || roundAny))
    val overflowUp = nearEven || nearMax || magUp
    val pegMin = common && totalUnderflow && (magUp || odd)
    val pegMax = overflow && !overflowUp
    val isInf = inputInf || (overflow && overflowUp)
    val exp = (roundedExponent(e, 0) &
        ~Mux(inputZero || totalUnderflow, nanExp.U((e + 1).W), 0.U) &
        ~Mux(pegMin, ~minNonzero.U((e + 1).W), 0.U) &
        ~Mux(pegMax, (BigInt(1) << (e - 1)).U((e + 1).W), 0.U) &
        ~Mux(isInf, (BigInt(1) << (e - 2)).U((e + 1).W), 0.U)) |
        Mux(pegMin, minNonzero.U((e + 1).W), 0.U) | Mux(pegMax, maxExp.U((e + 1).W), 0.U) |
        Mux(isInf, infExp.U((e + 1).W), 0.U) | Mux(isNaN, nanExp.U((e + 1).W), 0.U)
    val fraction = Mux(isNaN || inputZero || totalUnderflow,
        Mux(isNaN, (BigInt(1) << (s - 2)).U, 0.U), rounded(s - 2, 0)) | Fill(s - 1, pegMax)
    val value = RegEnable(Cat(Mux(isNaN, false.B, inputSign), exp, fraction), roundedValid && !io.flush)
    val flags = RegEnable(Cat(invalid, false.B, overflow, underflow, inexact), roundedValid && !io.flush)
    val nan = RegEnable(isNaN, roundedValid && !io.flush)
    val resultValid = RegNext(roundedValid && !io.flush, false.B)
    io.result.valid := resultValid && !io.flush
    io.result.bits.value := value; io.result.bits.flags := flags; io.result.bits.nan := nan
    when(io.flush) { prepared := false.B; maskValid := false.B; roundedValid := false.B; resultValid := false.B }
}

