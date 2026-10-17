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

/** FPGA cuts around the pinned HardFloat FMA pre/post transformations.
  * Same single owner and exact full product/sticky bits, no numerical rounding
  * between stages. The compact implementation remains independently selectable.
  * Raw latency: ordinary multiply five edges, FMA nine; common raw/round follows.
  * Unchanged HardFloat sources/license: MulAddRecFN.scala and MulRecFN.scala.
  */
class I1FloatingPointRawMultiplyFusedCuts(p: FiveStageConfig, double: Boolean,
    preparedNormalization: Boolean = false) extends Module {
    val e = if (double) 11 else 8
    val s = if (double) 53 else 24
    val io = IO(new I1FloatingPointRawProducerIO(p, e, s))
    val normalization = if (preparedNormalization)
        Some(IO(Input(Vec(3, UInt(log2Ceil(s).W))))) else None
    override def desiredName: String = "I1FloatingPointRawMultiplyFusedCuts" + (if (double) "D" else "S")
    val recoded = Reg(Vec(3, UInt((e + s + 1).W)))
    val op = Reg(UInt(2.W))
    val fused = Reg(Bool())
    val recodedValid = RegNext(io.start.valid && !io.flush, false.B)
    when(io.start.valid && !io.flush) {
        for (i <- 0 until 3) {
            val ieee = I1FloatingPointFormat.operand(io.start.bits.operands(i), double)
            val value = if (preparedNormalization)
                I1FloatingPointPredecodedRecoder(e, s, ieee, normalization.get(i))
                else recFNFromFN(e, s, ieee)
            if (preparedNormalization) {
                assert(normalization.get(i) === countLeadingZeros(ieee(s - 2, 0)) &&
                    value === recFNFromFN(e, s, ieee),
                    "prepared multiply/FMA normalization lost its captured operand")
            }
            recoded(i) := value
        }
        op := Cat(io.start.bits.command.instruction(3), io.start.bits.command.instruction(2))
        fused := I1FloatingPointDecode.fused(io.start.bits.command.instruction)
    }
    val a = Reg(new RawFloat(e, s))
    val b = Reg(new RawFloat(e, s))
    val c = Reg(new RawFloat(e, s))
    val rawValid = RegNext(recodedValid && !io.flush, false.B)
    when(recodedValid && !io.flush) {
        a := rawFloatFromRecFN(e, s, recoded(0))
        b := rawFloatFromRecFN(e, s, recoded(1))
        c := rawFloatFromRecFN(e, s, recoded(2))
    }

    // Seventeen-bit DSP tiles with registered products, then registered
    // carry-save row reduction and a final carry-save/one-adder reduction.
    // Never depend on an unregistered long DSP cascade plus a wide add.
    val productWidth = 2 * s
    val tiles = (s + 16) / 17
    def sum(values: Seq[UInt]): UInt = {
        val extended = values.map(_.pad(productWidth)(productWidth - 1, 0))
        if (extended.size == 3) {
            val x = extended(0); val y = extended(1); val z = extended(2)
            val carry = ((x & y) | (x & z) | (y & z)) << 1
            ((x ^ y ^ z) + carry)(productWidth - 1, 0)
        } else extended.reduce(_ + _)(productWidth - 1, 0)
    }
    val tileProducts = Seq.tabulate(tiles, tiles) { (i, j) =>
        val left = a.sig(math.min(s - 1, (i + 1) * 17 - 1), i * 17)
        val right = b.sig(math.min(s - 1, (j + 1) * 17 - 1), j * 17)
        RegEnable(left * right, rawValid && !io.flush)
    }
    val tilesValid = RegNext(rawValid && !io.flush, false.B)
    val rows = Seq.tabulate(tiles) { i =>
        RegEnable(sum(Seq.tabulate(tiles)(j => tileProducts(i)(j) << ((i + j) * 17))),
            tilesValid && !io.flush)
    }
    val rowsValid = RegNext(tilesValid && !io.flush, false.B)
    val product = RegEnable(sum(rows), rowsValid && !io.flush)
    val productValid = RegNext(rowsValid && !io.flush, false.B)

    // Pinned preMul equations, separated at exponent sum and alignment
    // distance. This preserves every exceptional and low sticky bit.
    val sigSumWidth = 3 * s + 3
    val alignedExponent = a.sExp +& b.sExp + (-(BigInt(1) << e) + s + 3).S
    val alignedExponentReg = RegEnable(alignedExponent, rawValid && !io.flush)
    val exponentValid = RegNext(rawValid && !io.flush, false.B)
    val signProd = a.sign ^ b.sign ^ op(1)
    val subtract = signProd ^ c.sign ^ op(0)
    val naturalDistance = alignedExponentReg - c.sExp
    val positiveDistance = naturalDistance(e + 1, 0)
    val minimum = a.isZero || b.isZero || naturalDistance < 0.S
    val dominant = !c.isZero && (minimum || positiveDistance <= s.U)
    val distance = Mux(minimum, 0.U, Mux(positiveDistance < (sigSumWidth - 1).U,
        positiveDistance(log2Ceil(sigSumWidth) - 1, 0), (sigSumWidth - 1).U))
    val distanceReg = RegEnable(distance, exponentValid && !io.flush)
    val dominantReg = RegEnable(dominant, exponentValid && !io.flush)
    val exponentSum = Mux(dominant, c.sExp, (alignedExponentReg - s.S)(e + 1, 0).asSInt)
    val exponentSumReg = RegEnable(exponentSum, exponentValid && !io.flush)
    val distanceValid = RegNext(exponentValid && !io.flush, false.B)
    val mainAligned = (Mux(subtract, ~c.sig, c.sig) ##
        Fill(sigSumWidth - s + 2, subtract)).asSInt >> distanceReg
    val extra = (orReduceBy4(c.sig << ((sigSumWidth - s - 1) & 3)) &
        lowMask(distanceReg >> 2, (sigSumWidth - 1) >> 2, (sigSumWidth - s - 1) >> 2)).orR
    val aligned = Cat(mainAligned >> 3, Mux(subtract,
        mainAligned(2, 0).andR && !extra, mainAligned(2, 0).orR || extra))
    val alignedC = Reg(UInt((2 * s).W))
    val metadata = Reg(new MulAddRecFN_interIo(e, s))
    when(distanceValid && !io.flush) {
        alignedC := aligned(2 * s, 1)
        metadata.isSigNaNAny := isSigNaNRawFloat(a) || isSigNaNRawFloat(b) || isSigNaNRawFloat(c)
        metadata.isNaNAOrB := a.isNaN || b.isNaN
        metadata.isInfA := a.isInf; metadata.isZeroA := a.isZero
        metadata.isInfB := b.isInf; metadata.isZeroB := b.isZero
        metadata.signProd := signProd
        metadata.isNaNC := c.isNaN; metadata.isInfC := c.isInf; metadata.isZeroC := c.isZero
        metadata.sExpSum := exponentSumReg
        metadata.doSubMags := subtract; metadata.CIsDominant := dominantReg
        metadata.CDom_CAlignDist := distanceReg(log2Ceil(s + 1) - 1, 0)
        metadata.highAlignedSigC := aligned(sigSumWidth - 1, 2 * s + 1)
        metadata.bit0AlignedSigC := aligned(0)
    }
    val alignmentValid = RegNext(distanceValid && !io.flush, false.B)
    val fusedProduct = Reg(UInt((2 * s + 1).W))
    val fusedMetadata = Reg(new MulAddRecFN_interIo(e, s))
    val fusedValid = RegNext(productValid && fused && !io.flush, false.B)
    when(productValid && fused && !io.flush) {
        assert(alignmentValid, "FMA alignment and exact product retain the same owner")
        fusedProduct := product +& alignedC
        fusedMetadata := metadata
    }
    val post = Module(new I1FloatingPointPostMulCuts(e, s))
    post.io.metadata := fusedMetadata; post.io.product := fusedProduct
    post.io.rounding := io.rounding; post.io.valid := fusedValid; post.io.flush := io.flush
    val ordinary = Wire(new I1FloatingPointRawResult(e, s))
    ordinary.invalid := isSigNaNRawFloat(a) || isSigNaNRawFloat(b) ||
        (a.isInf && b.isZero) || (a.isZero && b.isInf)
    ordinary.infinite := false.B
    ordinary.value.isNaN := a.isNaN || b.isNaN
    ordinary.value.isInf := a.isInf || b.isInf; ordinary.value.isZero := a.isZero || b.isZero
    ordinary.value.sign := a.sign ^ b.sign
    ordinary.value.sExp := a.sExp + b.sExp - (BigInt(1) << e).S
    ordinary.value.sig := Cat(product >> (s - 2), product(s - 3, 0).orR)
    val fusedResult = Wire(new I1FloatingPointRawResult(e, s))
    fusedResult := post.io.result.bits
    io.result.valid := ((productValid && !fused) || post.io.result.valid) && !io.flush
    io.result.bits := Mux(post.io.result.valid, fusedResult, ordinary)
    when(io.flush) {
        recodedValid := false.B; rawValid := false.B; tilesValid := false.B
        rowsValid := false.B; productValid := false.B; exponentValid := false.B
        distanceValid := false.B; alignmentValid := false.B; fusedValid := false.B
    }
    when(productValid && !io.flush) {
        assert(!a.sig(s) && !b.sig(s), "tiled product excludes only the recoded leading zero")
    }
}
