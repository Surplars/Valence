package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.CoherentCacheConcurrency

class CoherentCacheConcurrencySpec extends AnyFunSuite {
    test("read miss capacity does not silently change response or writeback capacity") {
        for (m <- Seq(1, 2, 4); responses <- Seq(4, 8, 16)) {
            val c = CoherentCacheConcurrency(m, responses)
            assert(c.readMshrs == m && c.responseEntries == responses && c.writebackEntries == 1)
            assert(c.releaseSource >= c.acquireEntries)
            assert((1 << c.sourceBits) > c.releaseSource)
            assert((1 << c.sinkBits) >= m)
        }
    }
    test("unsupported or underprovisioned capacities are rejected") {
        for (m <- Seq(0, 3, 8)) intercept[IllegalArgumentException](CoherentCacheConcurrency(m))
        for (r <- Seq(0, 1, 3, 32)) intercept[IllegalArgumentException](CoherentCacheConcurrency(2, r))
        intercept[IllegalArgumentException](CoherentCacheConcurrency(4, 2))
        intercept[IllegalArgumentException](CoherentCacheConcurrency(4))
        intercept[IllegalArgumentException](CoherentCacheConcurrency(writebackEntries = 2))
    }
}
