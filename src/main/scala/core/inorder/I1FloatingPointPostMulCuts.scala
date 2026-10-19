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
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES
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

/** Exact pinned postMul equations, retimed at sum, absolute significand and
  * normalization distance. No rounding/truncation is introduced at the cuts.
  * One parent owner; +3 FMA cycles, ordinary multiply latency unchanged.
  * Origin: pinned HardFloat MulAddRecFNToRaw_postMul, never edit the vendor.
  */
class I1FloatingPointPostMulCuts(e: Int, s: Int) extends Module {
    val io = IO(new Bundle {
        val valid = Input(Bool()); val flush = Input(Bool())
        val metadata = Input(new MulAddRecFN_interIo(e, s))
        val product = Input(UInt((2 * s + 1).W))
        val rounding = Input(UInt(3.W))
        val result = Output(Valid(new I1FloatingPointRawResult(e, s)))
    })
    val width = 3 * s + 3
    val v1 = RegNext(io.valid && !io.flush, false.B)
    val m1 = RegEnable(io.metadata, io.valid && !io.flush)
    val sum = RegEnable(Cat(Mux(io.product(2 * s),
        io.metadata.highAlignedSigC + 1.U, io.metadata.highAlignedSigC),
        io.product(2 * s - 1, 0), io.metadata.bit0AlignedSigC), io.valid && !io.flush)

    // Carry/complement terminates here, before LZD and the normalization shifter.
    val v2 = RegNext(v1 && !io.flush, false.B)
    val m2 = RegEnable(m1, v1 && !io.flush)
    val cAbs = RegEnable(Mux(m1.doSubMags, ~sum(width - 1, s + 1),
        Cat(0.U(1.W), m1.highAlignedSigC(s + 1, s), sum(width - 3, s + 2))), v1 && !io.flush)
    val cExtra = RegEnable(Mux(m1.doSubMags, (~sum(s, 1)).orR,
        sum(s + 1, 1).orR), v1 && !io.flush)
    val sign = RegEnable(sum(2 * s + 3), v1 && !io.flush)
    val absolute = RegEnable(Mux(sum(2 * s + 3), ~sum(2 * s + 2, 0),
        sum(2 * s + 2, 0) + m1.doSubMags), v1 && !io.flush)

    val reduced2 = orReduceBy2(absolute)
    val normDistance = countLeadingZeros(reduced2)
    val cMain = (cAbs << m2.CDom_CAlignDist)(2 * s + 1, s - 3)
    val cReducedExtra = (orReduceBy4(cAbs(s - 1, 0) << (~s & 3)) &
        lowMask(m2.CDom_CAlignDist >> 2, 0, s >> 2)).orR
    val cSig = Cat(cMain >> 3, cMain(2, 0).orR || cReducedExtra || cExtra)

    // LZD terminates here. Wide shifter and exponent correction are downstream.
    val v3 = RegNext(v2 && !io.flush, false.B)
    val m3 = RegEnable(m2, v2 && !io.flush)
    val distance3 = RegEnable(normDistance, v2 && !io.flush)
    val absolute3 = RegEnable(absolute, v2 && !io.flush)
    val reduced3 = RegEnable(reduced2, v2 && !io.flush)
    val sign3 = RegEnable(sign, v2 && !io.flush)
    val cSig3 = RegEnable(cSig, v2 && !io.flush)
    val cExp3 = RegEnable(m2.sExpSum - m2.doSubMags.zext, v2 && !io.flush)
    val nearDistance = distance3 << 1
    val notCExp = m3.sExpSum - nearDistance.asUInt.zext
    val notCMain = (absolute3 << nearDistance)(2 * s + 3, s - 1)
    val notCExtra = (orReduceBy2(reduced3(s >> 1, 0) << ((s >> 1) & 1)) &
        lowMask(distance3 >> 1, 0, (s + 2) >> 2)).orR
    val notCSig = Cat(notCMain >> 3, notCMain(2, 0).orR || notCExtra)
    val cancellation = notCSig(s + 2, s + 1) === 0.U
    val roundMin = io.rounding === round_min
    val cSign = m3.signProd ^ m3.doSubMags
    val notCSign = Mux(cancellation, roundMin, m3.signProd ^ sign3)
    val infProd = m3.isInfA || m3.isInfB
    val infOut = infProd || m3.isInfC
    val zeros = (m3.isZeroA || m3.isZeroB) && m3.isZeroC
    io.result.valid := v3 && !io.flush
    io.result.bits.infinite := false.B
    io.result.bits.invalid := m3.isSigNaNAny ||
        (m3.isInfA && m3.isZeroB) || (m3.isZeroA && m3.isInfB) ||
        (!m3.isNaNAOrB && infProd && m3.isInfC && m3.doSubMags)
    io.result.bits.value.isNaN := m3.isNaNAOrB || m3.isNaNC
    io.result.bits.value.isInf := infOut
    io.result.bits.value.isZero := zeros || (!m3.CIsDominant && cancellation)
    io.result.bits.value.sign := (infProd && m3.signProd) || (m3.isInfC && cSign) ||
        (zeros && !roundMin && m3.signProd && cSign) ||
        (zeros && roundMin && (m3.signProd || cSign)) ||
        (!infOut && !zeros && Mux(m3.CIsDominant, cSign, notCSign))
    io.result.bits.value.sExp := Mux(m3.CIsDominant, cExp3, notCExp)
    io.result.bits.value.sig := Mux(m3.CIsDominant, cSig3, notCSig)
    when(io.flush) { v1 := false.B; v2 := false.B; v3 := false.B }
}
