package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class DataPrefetchConfigSpec extends AnyFunSuite {
    test("default-off prefetch does not grow any capacity") {
        val (args, config) = MixedMemoryConfig.parseArgs(Array("image", "--data-next-line-prefetch"))
        assert(args.sameElements(Array("image")))
        val c = config.cache(CoherentCacheConcurrency(2))
        assert(c.nextLinePrefetch && c.readMshrs == 2 && c.responseEntries == 2 && c.writebackEntries == 1)
        assert(!MixedMemoryConfig().cache(CoherentCacheConcurrency(2)).nextLinePrefetch)
        assert(!BoardSocConfig.boardParams("staged-fetch-turnover").dataNextLinePrefetch)
        assert(BoardSocConfig.boardParams("staged-fetch-turnover", dataNextLinePrefetch = true).dataNextLinePrefetch)
    }
    test("bounded candidate lifetime preserves every ownership capacity") {
        for (cycles <- Seq(1, 3, 16)) {
            val c = CoherentCacheConcurrency(2, 2, 2, overlapWritebackRefill = true,
                nextLinePrefetch = true, prefetchCandidateCycles = cycles)
            assert(c.readMshrs == 2 && c.responseEntries == 2 && c.writebackEntries == 2)
            assert(c.prefetchCandidateCycles == cycles)
        }
        assert(CoherentCacheConcurrency(2).prefetchCandidateCycles == 1)
        for (cycles <- Seq(0, 33)) intercept[IllegalArgumentException](
            CoherentCacheConcurrency(2, nextLinePrefetch = true, prefetchCandidateCycles = cycles))
        intercept[IllegalArgumentException](CoherentCacheConcurrency(2, prefetchCandidateCycles = 3))
    }
    test("accepted-store history option is explicit and preserves every capacity") {
        val base = CoherentCacheConcurrency(2, 2, 2, overlapWritebackRefill = true,
            nextLinePrefetch = true, prefetchCandidateCycles = 3)
        assert(!base.prefetchBreakOnStore)
        val candidate = base.copy(prefetchBreakOnStore = true)
        assert(candidate.copy(prefetchBreakOnStore = false) == base)
        intercept[IllegalArgumentException](CoherentCacheConcurrency(2, prefetchBreakOnStore = true))
    }
    test("reject unsupported ownership and unprotected authorization boundaries") {
        intercept[IllegalArgumentException](CoherentCacheConcurrency(nextLinePrefetch = true))
        intercept[IllegalArgumentException](OooParams(dataNextLinePrefetch = true))
        intercept[IllegalArgumentException](MixedMemoryConfig.parseArgs(Array("--data-next-line-prefetch", "--data-next-line-prefetch")))
        intercept[IllegalArgumentException](MixedMemoryConfig.parseArgs(Array("--data-next-line-prefetch=1")))
    }
}
