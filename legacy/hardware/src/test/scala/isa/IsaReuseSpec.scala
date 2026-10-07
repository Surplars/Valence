package isa

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.config.ISAProfiles
import soc.core.pipeline.InstrDecode
import soc.isa.Extension

class IsaReuseSpec extends AnyFunSuite {
    test("legacy control adapters still elaborate with shared ISA definitions and explicit extension sets") {
        for (extensions <- Seq(Set(Extension.RV64I), ISAProfiles.RV64IMACB)) {
            val firrtl = ChiselStage.emitCHIRRTL(new InstrDecode(enabledExt = extensions))
            assert(firrtl.contains("module InstrDecode"))
            assert(!firrtl.contains("UInt<0>"))
        }
    }
}
