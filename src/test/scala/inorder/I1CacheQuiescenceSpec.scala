package inorder

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.inorder._

class I1CacheQuiescenceSpec extends AnyFunSuite {
    test("private cache quiescence observation is absent by default") {
        val ordinary = ChiselStage.emitCHIRRTL(new I1CoherentLineCache(lines = 4))
        val explicitOff = ChiselStage.emitCHIRRTL(new I1CoherentLineCache(lines = 4,
            reportQuiescence = false))
        assert(!ordinary.contains("quiescent"))
        assert(ordinary == explicitOff)
        val enabled = ChiselStage.emitCHIRRTL(new I1CoherentLineCache(lines = 4,
            reportQuiescence = true))
        assert(enabled.contains("quiescent"))
    }
}
