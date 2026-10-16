package ooo

import org.scalatest.funsuite.AnyFunSuite

/** Pure JSON serialization regression: no elaboration, simulator, or native emission. */
class CombinedBandwidthInventoryJsonSpec extends AnyFunSuite {
    test("inventory byte sizes are numeric JSON and round-trip exactly") {
        for (size <- Seq(0L, 5719L, Int.MaxValue.toLong + 1L, (1L << 53) - 1L)) {
            val rendered = ujson.Obj("bytes" -> CombinedBandwidthInventoryJson.bytes(size)).render()
            val decoded = ujson.read(rendered)("bytes")
            assert(decoded.isInstanceOf[ujson.Num])
            assert(decoded.num == size.toDouble && decoded.num.toLong == size)
            assert(!rendered.contains("\"bytes\":\""))
        }
    }

    test("negative or potentially inexact inventory sizes fail closed") {
        for (size <- Seq(-1L, 1L << 53, (1L << 53) + 1L, Long.MaxValue)) {
            intercept[IllegalArgumentException] {
                CombinedBandwidthInventoryJson.bytes(size)
            }
        }
    }
}
