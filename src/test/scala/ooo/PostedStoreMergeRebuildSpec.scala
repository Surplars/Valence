package ooo

import org.scalatest.funsuite.AnyFunSuite
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Authored checks awaiting the parent-granted compile/elaboration slot. No simulation. */
class PostedStoreMergeRebuildSpec extends AnyFunSuite {
    private val on = PostedStoreMergeConfig(enabled = true,
        guaranteedBase = BigInt("80010000", 16), guaranteedBytes = 32768)

    test("standalone reconstruction is default off with original capacity options") {
        assert(!PostedStoreMergeConfig().enabled)
        for (m <- Seq(1, 2, 4); w <- Seq(1, 2, 4) if m > 1 || w == 1) {
            val cfg = PostedStoreMergeConfig(readMshrs = m, writebackEntries = w,
                responseEntries = math.max(2, m))
            assert(!cfg.enabled)
        }
    }

    test("ON requires the explicit successful RAM contract and initial two-MSHR geometry") {
        intercept[IllegalArgumentException] { PostedStoreMergeConfig(enabled = true) }
        intercept[IllegalArgumentException] { on.copy(readMshrs = 1) }
        intercept[IllegalArgumentException] { on.copy(readMshrs = 4) }
        intercept[IllegalArgumentException] { on.copy(guaranteedBase = on.guaranteedBase + 1) }
        intercept[IllegalArgumentException] { on.copy(guaranteedBytes = on.guaranteedBytes - 1) }
        for (w <- Seq(1, 2, 4)) { assert(on.copy(writebackEntries = w).enabled) }
        assert(on.copy(generationBits = 2).generationBits == 2)
        on.requireCacheAperture(on.guaranteedBase, on.guaranteedBytes)
        intercept[IllegalArgumentException] { on.requireCacheAperture(on.guaranteedBase, on.guaranteedBytes - 64) }
        intercept[IllegalArgumentException] { on.requireCacheAperture(on.guaranteedBase + 64, on.guaranteedBytes) }
    }

    test("disabled standalone owner has no state; enabled interface elaborates") {
        val off = ChiselStage.emitCHIRRTL(new PostedStoreMerge(on.copy(enabled = false)))
        assert("""(?m)^\s*(reg|regreset)\s""".r.findFirstIn(off).isEmpty)
        val enabled = ChiselStage.emitCHIRRTL(new PostedStoreMerge(on))
        assert(enabled.contains("regreset live") && enabled.contains("regreset nextGeneration"))
        assert(enabled.contains("writebackSent") && enabled.contains("cacheAdmission"))
    }
}
