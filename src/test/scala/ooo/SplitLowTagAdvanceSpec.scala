package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.SplitLowTagAdvance

class SplitLowTagAdvanceSpec extends AnyFunSuite {
    private class WidthFixture(baseBits: Int, countBits: Int) extends RawModule {
        val base = IO(Input(if (baseBits < 0) UInt() else UInt(baseBits.W)))
        val count = IO(Input(if (countBits < 0) UInt() else UInt(countBits.W)))
        val result = SplitLowTagAdvance(base, count)
        require(result.getWidth == baseBits + 1, "full overflow bit must be retained")
        val out = IO(Output(UInt((baseBits + 1).W)))
        out := result
    }

    test("generic counted advance retains B+1 result bits for supported known widths") {
        for ((b, c) <- Seq((2, 1), (3, 2), (64, 2))) {
            val fir = ChiselStage.emitCHIRRTL(new WidthFixture(b, c))
            assert(fir.contains(s"output out : UInt<${b + 1}>"))
        }
    }

    test("equal narrower zero and unknown widths fail closed at elaboration") {
        for ((b, c) <- Seq((2, 2), (1, 2), (64, 0), (0, 1), (-1, 2), (64, -1))) {
            // Unknown getWidth is rejected by Chisel itself; known invalid widths
            // are rejected by the helper require. Neither may silently infer/truncate.
            intercept[Exception] { ChiselStage.emitCHIRRTL(new WidthFixture(b, c)) }
        }
    }
}
