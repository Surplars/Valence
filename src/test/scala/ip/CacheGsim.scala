package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.memory.SharedReadCache

object CacheGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new SharedReadCache(), Array("--target-dir", args.head))
}
class CacheParamsSpec extends AnyFunSuite {
    test("shared cache has power-of-two geometry and whole RAM reservation granules") {
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new SharedReadCache(lines = 3)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new SharedReadCache(base = 8)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new SharedReadCache(bytes = 65)) }
        assert(ChiselStage.emitCHIRRTL(new SharedReadCache(base = 64, bytes = 64, lines = 2)).contains("smem"))
    }
}
