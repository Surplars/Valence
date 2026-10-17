
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

// Local shared-product adaptation of the pinned MulRawFN transformation.
package soc.core.ooo

import chisel3._
import chisel3.util._
import hardfloat._

/** One significand multiplier per format for ordinary multiply and fused multiply-add.
  * Both pinned HardFloat paths multiply exactly the same recoded significands.
  * The common operands are registered directly, with no operation-select mux.
  * Ordinary multiply captures its raw result after that multiplier. FMA retains
  * the full product/add register before the pinned postMul normalization block.
  * The two result paths therefore preserve the existing 3/4 cycle latencies.
  *
  * MulRawFN's special-value/exponent/sticky transformation is reproduced here
  * around the shared full product; the pinned implementation and license remain
  * in third_party/berkeley-hardfloat/src/main/scala/MulRecFN.scala. No intermediate
  * product is rounded, and all low product bits feed the sticky reduction.
  */
class FloatingPointRawMultiplyFused(p: OooParams, double: Boolean) extends Module {
    val e = if (double) 11 else 8
    val s = if (double) 53 else 24
    val io = IO(new FloatingPointRawProducerIO(p, e, s))
    override def desiredName: String = s"FloatingPointRawMultiplyFused${if (double) "D" else "S"}"
    def rec(lane: Int): UInt = recFNFromFN(e, s, FloatingPointFormat.operand(io.start.bits.operands(lane), double))
    val offeredA = rec(0)
    val offeredB = rec(1)
    val a = Reg(new RawFloat(e, s))
    val b = Reg(new RawFloat(e, s))
    val fused = Reg(Bool())
    val prepared = RegNext(io.start.valid && !io.flush, false.B)
    val pre = Module(new MulAddRecFNToRaw_preMul(e, s))
    pre.io.op := Cat(io.start.bits.command.instruction(3), io.start.bits.command.instruction(2))
    pre.io.a := offeredA; pre.io.b := offeredB; pre.io.c := rec(2)
    val c = Reg(chiselTypeOf(pre.io.mulAddC))
    val metadata = Reg(chiselTypeOf(pre.io.toPostMul))
    when(io.start.valid && !io.flush) {
        a := rawFloatFromRecFN(e, s, offeredA)
        b := rawFloatFromRecFN(e, s, offeredB)
        fused := FloatingPointDecode.fused(io.start.bits.command.instruction)
        c := pre.io.mulAddC
        metadata := pre.io.toPostMul
    }
    // rawFloatFromRecFN always supplies a zero extension bit above bit s-1.
    // The exact common product is 2*s bits, including its full low tail.
    val product = a.sig(s - 1, 0) * b.sig(s - 1, 0)
    val multiplication = Wire(new FloatingPointRawResult(e, s))
    multiplication.invalid := isSigNaNRawFloat(a) || isSigNaNRawFloat(b) ||
        (a.isInf && b.isZero) || (a.isZero && b.isInf)
    multiplication.infinite := false.B
    multiplication.value.isNaN := a.isNaN || b.isNaN
    multiplication.value.isInf := a.isInf || b.isInf
    multiplication.value.isZero := a.isZero || b.isZero
    multiplication.value.sign := a.sign ^ b.sign
    multiplication.value.sExp := a.sExp + b.sExp - (BigInt(1) << e).S
    multiplication.value.sig := Cat(product >> (s - 2), product(s - 3, 0).orR)

    val fusedProduct = Reg(UInt((2 * s + 1).W))
    val fusedMetadata = Reg(chiselTypeOf(pre.io.toPostMul))
    val fusedValid = RegNext(prepared && fused && !io.flush, false.B)
    when(prepared && fused && !io.flush) {
        fusedProduct := product +& c
        fusedMetadata := metadata
    }
    val post = Module(new MulAddRecFNToRaw_postMul(e, s))
    post.io.fromPreMul := fusedMetadata
    post.io.mulAddResult := fusedProduct
    post.io.roundingMode := io.rounding
    val fusedResult = Wire(new FloatingPointRawResult(e, s))
    fusedResult.value := post.io.rawOut
    fusedResult.invalid := post.io.invalidExc
    fusedResult.infinite := false.B
    io.result.valid := ((prepared && !fused) || fusedValid) && !io.flush
    io.result.bits := Mux(fusedValid, fusedResult, multiplication)
    when(io.flush) { prepared := false.B; fusedValid := false.B }
    when(prepared && !io.flush) {
        assert(!a.sig(s) && !b.sig(s), "common multiplier inputs retain the recoded leading zero")
    }
}
