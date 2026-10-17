/*
 * Derived from pinned Berkeley HardFloat RecFNToIN.scala; arithmetic identities
 * and exception rules retained, with an I1-owned register after alignment.
 *
 * Copyright 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018 The Regents of
 * the University of California. All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 * 1. Redistributions of source code must retain the above copyright notice,
 *    this list of conditions, and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright notice,
 *    this list of conditions, and the following disclaimer in the documentation
 *    and/or other materials provided with the distribution.
 * 3. Neither the name of the University nor the names of its contributors may
 *    be used to endorse or promote products derived from this software without
 *    specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE REGENTS AND CONTRIBUTORS "AS IS", AND ANY
 * EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
 * WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE, ARE
 * DISCLAIMED. IN NO EVENT SHALL THE REGENTS OR CONTRIBUTORS BE LIABLE FOR ANY
 * DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
 * (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
 * LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
 * ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
 * SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */
package soc.core.inorder

import chisel3._
import chisel3.util._
import hardfloat._
import hardfloat.consts._

/** One existing miscellaneous owner; caller captures once before consuming.
  * No vendor files, rounding policy or saturation values are changed.
  */
class I1FloatingPointToIntegerCuts(e: Int, s: Int, width: Int) extends Module {
    val io = IO(new Bundle {
        val in = Input(UInt((e + s + 1).W))
        val roundingMode = Input(UInt(3.W)); val signedOut = Input(Bool())
        val capture = Input(Bool())
        val out = Output(UInt(width.W)); val intExceptionFlags = Output(UInt(3.W))
    })
    val raw = rawFloatFromRecFN(e, s, io.in)
    val geOne = raw.sExp(e)
    val shifted = Cat(geOne, raw.sig(s - 2, 0)) <<
        Mux(geOne, raw.sExp(math.min(e - 2, log2Ceil(width) - 1), 0), 0.U)
    val aligned = Cat(shifted >> (s - 2), shifted(s - 3, 0).orR)
    // This is the full pinned alignedSig, including guard/sticky bits.
    // Sideband classification and rounding travel through the same edge.
    val alignedSig = RegEnable(aligned, io.capture)
    val magGeOne = RegEnable(geOne, io.capture)
    val posExp = RegEnable(raw.sExp(e - 1, 0), io.capture)
    val sign = RegEnable(raw.sign, io.capture)
    val isZero = RegEnable(raw.isZero, io.capture)
    val isNaN = RegEnable(raw.isNaN, io.capture)
    val isInf = RegEnable(raw.isInf, io.capture)
    val signedOut = RegEnable(io.signedOut, io.capture)
    val mode = RegEnable(io.roundingMode, io.capture)
    val justBelowOne = !magGeOne && posExp.andR
    val nearEven = mode === round_near_even
    val nearMax = mode === round_near_maxMag
    val minimum = mode === round_min
    val maximum = mode === round_max
    val odd = mode === round_odd
    val unrounded = 0.U(width.W) | (alignedSig >> 2)
    val commonInexact = Mux(magGeOne, alignedSig(1, 0).orR, !isZero)
    val nearEvenIncrement =
        (magGeOne && (alignedSig(2, 1).andR || alignedSig(1, 0).andR)) ||
        (justBelowOne && alignedSig(1, 0).orR)
    val nearMaxIncrement = (magGeOne && alignedSig(1)) || justBelowOne
    val increment = (nearEven && nearEvenIncrement) || (nearMax && nearMaxIncrement) ||
        ((minimum || odd) && sign && commonInexact) || (maximum && !sign && commonInexact)
    val complement = Mux(sign, ~unrounded, unrounded)
    val rounded = Mux(increment ^ sign, complement + 1.U, complement) | (odd && commonInexact)
    val edge = posExp === (width - 1).U
    val carryButTwo = unrounded(width - 3, 0).andR && increment
    val commonOverflow = Mux(magGeOne,
        posExp >= width.U || Mux(signedOut,
            Mux(sign, edge && (unrounded(width - 2, 0).orR || increment),
                edge || ((posExp === (width - 2).U) && carryButTwo)),
            sign || (edge && unrounded(width - 2) && carryButTwo)),
        !signedOut && sign && increment)
    val invalid = isNaN || isInf
    val overflow = !invalid && commonOverflow
    val inexact = !invalid && !commonOverflow && commonInexact
    val exceptionSign = !isNaN && sign
    val exceptionValue = Mux(signedOut === exceptionSign,
        (BigInt(1) << (width - 1)).U, 0.U) |
        Mux(!exceptionSign, ((BigInt(1) << (width - 1)) - 1).U, 0.U)
    io.out := Mux(invalid || commonOverflow, exceptionValue, rounded)
    io.intExceptionFlags := Cat(invalid, overflow, inexact)
}
