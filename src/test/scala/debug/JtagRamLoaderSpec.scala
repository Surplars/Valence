package debug

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.debug.JtagRamLoader

class JtagRamLoaderSpec extends AnyFunSuite {
    test("RAM loader elaborates a bounded single-clock DMA and truthful absent DM") {
        val text = ChiselStage.emitCHIRRTL(new JtagRamLoader(BigInt("80200000", 16), BigInt("80300000", 16), timeoutCycles = 64))
        assert(text.contains("module JtagRamLoader"))
        assert(text.contains("linkUp : UInt<1>"))
        assert(!text.contains("haltRequest"))
    }
    test("invalid address windows are rejected") {
        for ((base, end) <- Seq((0, 0), (1, 16), (0, 15))) {
            intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new JtagRamLoader(base, end)) }
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new JtagRamLoader(0, BigInt(1) << 32))
        }
    }
}
object JtagRamLoaderGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new JtagRamLoader(BigInt("80200000", 16), BigInt("80201000", 16),
        timeoutCycles = 64), Array("--target-dir", args.head))
}
