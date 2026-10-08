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
    test("reject unsupported ownership and unprotected authorization boundaries") {
        intercept[IllegalArgumentException](CoherentCacheConcurrency(nextLinePrefetch = true))
        intercept[IllegalArgumentException](OooParams(dataNextLinePrefetch = true))
        intercept[IllegalArgumentException](MixedMemoryConfig.parseArgs(Array("--data-next-line-prefetch", "--data-next-line-prefetch")))
        intercept[IllegalArgumentException](MixedMemoryConfig.parseArgs(Array("--data-next-line-prefetch=1")))
    }
}
