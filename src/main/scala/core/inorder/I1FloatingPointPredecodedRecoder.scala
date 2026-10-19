/*============================================================================
This Chisel source file is derived from the HardFloat IEEE Floating-Point
Arithmetic Package, by John R. Hauser (with contributions from Yunsup Lee and
Andrew Waterman): rawFloatFromFN.scala and recFNFromFN.scala.

Copyright 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017 The Regents of the
University of California. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.
3. Neither the name of the University nor the names of its contributors may
   be used to endorse or promote products derived from this software without
   specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE REGENTS AND CONTRIBUTORS "AS IS" AND ANY
EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE, ARE
DISCLAIMED. IN NO EVENT SHALL THE REGENTS OR CONTRIBUTORS BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
============================================================================*/
package soc.core.inorder

import chisel3._
import chisel3.util._

/** Same pinned IEEE->recFN equations with leading-zero distance prepared at
  * the EXISTING dispatcher capture edge. No new numerical owner/latency.
  * Callers compare the complete recFN against the unchanged vendor function.
  */
object I1FloatingPointPredecodedRecoder {
    def apply(e: Int, s: Int, in: UInt, distance: UInt): UInt = {
        val sign = in(e + s - 1)
        val exp = in(e + s - 2, s - 1)
        val fract = in(s - 2, 0)
        val zeroExp = exp === 0.U
        val zeroFract = fract === 0.U
        val subnormal = ((fract << distance)(s - 3, 0) << 1)
        val adjusted = Mux(zeroExp, distance ^ ((BigInt(1) << (e + 1)) - 1).U, exp) +
            ((BigInt(1) << (e - 1)).U | Mux(zeroExp, 2.U, 1.U))
        val zero = zeroExp && zeroFract
        val nan = adjusted(e, e - 1) === 3.U && !zeroFract
        Cat(sign, Mux(zero, 0.U(3.W), adjusted(e, e - 2)) | nan.asUInt,
            adjusted(e - 3, 0), Mux(zeroExp, subnormal, fract))
    }
}
