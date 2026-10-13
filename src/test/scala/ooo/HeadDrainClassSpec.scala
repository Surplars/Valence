package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class HeadDrainClassSpec extends AnyFunSuite {
    test("head-drain is appended default off and changes only the explicit core field") {
        assert(OooParams().productArity == 172 && OooParams().productElementName(159) == "predecodedHeadDrain")
        assert(OooParams().productElementName(160) == "retirementIntent" && !OooParams().retirementIntent)
        assert(!OooParams().predecodedHeadDrain)
        assert(HeadDrainTestProfile.on.copy(predecodedHeadDrain = false) == HeadDrainTestProfile.off)
        intercept[IllegalArgumentException] { OooParams(predecodedHeadDrain = true) }
        for (rows <- Seq(8, 16, 32, 64)) {
            val p = OooParams(robEntries = rows, machineSystem = true, predecodedHeadDrain = true)
            assert(p.robEntries == rows)
        }
    }
    test("the isolated classification boundary is combinational") {
        val fir = ChiselStage.emitCHIRRTL(new HeadDrainDecodeGsim)
        assert(!fir.linesIterator.exists(line => line.trim.startsWith("reg ") || line.trim.startsWith("regreset ")))
    }
}
