/*============================================================================

This Chisel source file is part of a pre-release version of the HardFloat IEEE
Floating-Point Arithmetic Package, by John R. Hauser (ported from Verilog to
Chisel by Andrew Waterman).

Copyright 2019, 2020 The Regents of the University of California.  All rights
reserved.

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

/** Exact pinned AddRawFN equations, split at magnitude/alignment/normalization
  * boundaries for FPGA. No intermediate rounding, no second numerical owner.
  * Raw latency six edges; shared raw/round registers yield latency 8 / II 9.
  * Metadata remains stable under the format parent's single-owner credit.
  * Compact profiles still use the unchanged vendor AddRawFN.
  */
class I1FloatingPointRawAddCuts(p: FiveStageConfig, double: Boolean,
    preparedNormalization: Boolean = false) extends Module {
    val e = if (double) 11 else 8
    val s = if (double) 53 else 24
    val distanceWidth = log2Ceil(s)
    val io = IO(new I1FloatingPointRawProducerIO(p, e, s))
    val normalization = if (preparedNormalization)
        Some(IO(Input(Vec(2, UInt(log2Ceil(s).W))))) else None
    override def desiredName: String = "I1FloatingPointRawAddCuts" + (if (double) "D" else "S")
    val a = Reg(new RawFloat(e, s))
    val b = Reg(new RawFloat(e, s))
    val subtract = Reg(Bool())
    val prepared = RegNext(io.start.valid && !io.flush, false.B)
    when(io.start.valid && !io.flush) {
        def rec(lane: Int): UInt = {
            val ieee = I1FloatingPointFormat.operand(io.start.bits.operands(lane), double)
            val value = if (preparedNormalization)
                I1FloatingPointPredecodedRecoder(e, s, ieee, normalization.get(lane))
                else recFNFromFN(e, s, ieee)
            if (preparedNormalization) {
                assert(normalization.get(lane) === countLeadingZeros(ieee(s - 2, 0)) &&
                    value === recFNFromFN(e, s, ieee),
                    "prepared add normalization lost its captured operand")
            }
            value
        }
        a := rawFloatFromRecFN(e, s, rec(0))
        b := rawFloatFromRecFN(e, s, rec(1))
        subtract := io.start.bits.command.instruction(27)
    }

    // Stage 2: exponent distance/classification before wide significand muxes.
    val effectiveB = b.sign ^ subtract
    val signsEqual = a.sign === effectiveB
    val difference = a.sExp - b.sExp
    val naturalDistance = Mux(difference < 0.S,
        b.sExp.asUInt - a.sExp.asUInt, a.sExp.asUInt - b.sExp.asUInt)(distanceWidth - 1, 0)
    val maximum = (difference >> distanceWidth) =/= 0.S &&
        ((difference >> distanceWidth) =/= -1.S || difference(distanceWidth - 1, 0) === 0.U)
    val distance = RegEnable(Mux(maximum, ((BigInt(1) << distanceWidth) - 1).U, naturalDistance),
        prepared && !io.flush)
    val close = RegEnable(!signsEqual && !maximum && naturalDistance <= 1.U, prepared && !io.flush)
    val negativeDifference = RegEnable(difference < 0.S, prepared && !io.flush)
    val oddDifference = RegEnable(difference(0), prepared && !io.flush)
    val equal = RegEnable(signsEqual, prepared && !io.flush)
    val effSignB = RegEnable(effectiveB, prepared && !io.flush)
    val classValid = RegNext(prepared && !io.flush, false.B)

    // Stage 3: exact alignment plus sticky; close subtraction is NOT here.
    val closeAligned = Mux(!negativeDifference && oddDifference, a.sig << 2, 0.U) |
        Mux(!negativeDifference && !oddDifference, a.sig << 1, 0.U) |
        Mux(negativeDifference, a.sig, 0.U)
    val larger = Mux(negativeDifference, b.sig, a.sig)(s - 1, 0)
    val smaller = Mux(negativeDifference, a.sig, b.sig)(s - 1, 0)
    val mainAligned = (smaller << 5) >> distance
    val extraMask = lowMask(distance(distanceWidth - 1, 2), (s + 5) / 4, 0)
    val aligned = Cat(mainAligned >> 3,
        mainAligned(2, 0).orR || (orReduceBy4(smaller << 2) & extraMask).orR)
    val closeAlignedReg = RegEnable(closeAligned, classValid && !io.flush)
    val largerReg = RegEnable(larger, classValid && !io.flush)
    val smallerReg = RegEnable(aligned, classValid && !io.flush)
    val alignValid = RegNext(classValid && !io.flush, false.B)

    // Stage 4: close signed sum and far exact sum, before absolute value/CLZ.
    val closeSum = RegEnable(closeAlignedReg.asSInt - (b.sig << 1).asSInt, alignValid && !io.flush)
    val farWidth = s + 4
    val x = (largerReg << 3).pad(farWidth)
    val y = Mux(!equal, Cat(1.U(1.W), ~smallerReg), smallerReg).pad(farWidth)
    val z = Mux(equal, 0.U(farWidth.W), 1.U(farWidth.W))
    // Carry save removes a chained two-adder expression; same modular width.
    val carry = (((x & y) | (x & z) | (y & z)) << 1)(farWidth - 1, 0)
    val farSum = RegEnable(((x ^ y ^ z) + carry)(farWidth - 1, 0), alignValid && !io.flush)
    val sumValid = RegNext(alignValid && !io.flush, false.B)

    // Stage 5: exact close absolute magnitude, NOT absolute -> CLZ -> barrel.
    val magnitude = RegEnable(Mux(closeSum < 0.S, -closeSum, closeSum)(s + 1, 0),
        sumValid && !io.flush)
    val magnitudeValid = RegNext(sumValid && !io.flush, false.B)

    // Stage 6: leading-zero distance registered before normalization barrel.
    val reduced = orReduceBy2(magnitude << (s & 1))
    val normDistance = RegEnable((countLeadingZeros(reduced) << 1)(distanceWidth - 1, 0),
        magnitudeValid && !io.flush)
    val normValid = RegNext(magnitudeValid && !io.flush, false.B)

    val closeOut = ((magnitude << normDistance) << 1)(s + 2, 0)
    val cancellation = !closeOut(s + 2, s + 1).orR
    val subtractMags = !equal
    val farOut = Mux(subtractMags, farSum, (farSum >> 1) | farSum(0))(s + 2, 0)
    val eitherInf = a.isInf || b.isInf
    val bothZero = a.isZero && b.isZero
    val special = eitherInf || bothZero
    val zero = bothZero || (!eitherInf && close && cancellation)
    val sign = (equal && a.sign) || (a.isInf && a.sign) || (b.isInf && effSignB) ||
        (zero && !equal && io.rounding === round_min) ||
        (!special && close && !cancellation && (a.sign ^ (closeSum < 0.S))) ||
        (!special && !close && Mux(negativeDifference, effSignB, a.sign))
    io.result.valid := normValid && !io.flush
    io.result.bits.invalid := isSigNaNRawFloat(a) || isSigNaNRawFloat(b) ||
        (a.isInf && b.isInf && !equal)
    io.result.bits.infinite := false.B
    io.result.bits.value.isNaN := a.isNaN || b.isNaN
    io.result.bits.value.isInf := eitherInf
    io.result.bits.value.isZero := zero
    io.result.bits.value.sign := sign
    io.result.bits.value.sExp := Mux(close || negativeDifference, b.sExp, a.sExp) -
        Mux(close, normDistance, subtractMags).zext
    io.result.bits.value.sig := Mux(close, closeOut, farOut)
    when(io.flush) {
        prepared := false.B; classValid := false.B; alignValid := false.B
        sumValid := false.B; magnitudeValid := false.B; normValid := false.B
    }
}
