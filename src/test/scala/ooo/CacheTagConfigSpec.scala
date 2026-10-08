package ooo

import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import soc.core.ooo._

class CacheTagConfigSpec extends AnyFlatSpec with Matchers {
    "CacheTagConfig" should "derive absolute tag width without narrowing the address contract" in {
        val base = BigInt("80200000", 16)
        val bytes = BigInt(1) << 31
        CacheTagConfig.FullWidth.geometry(base, bytes, 14).tagBits shouldBe 50
        CacheTagConfig.Aperture.geometry(base, bytes, 14).tagBits shouldBe 19
        CacheTagConfig.Aperture.geometry(base, bytes, 6).tagBits shouldBe 27
        CacheTagConfig.Aperture.geometry(BigInt("80000000", 16), bytes, 14).tagBits shouldBe 18
        CacheTagConfig.Aperture.geometry(0, 64, 14).tagBits shouldBe 1
        CacheTagConfig.Aperture.geometry((BigInt(1) << 64) - 64, 64, 14).tagBits shouldBe 50
        // Prefix truncation is exact only with full-address aperture membership.
        for ((b, n) <- Seq((base, bytes), (BigInt(0), BigInt(64)),
            (BigInt("123456000", 16), BigInt(192)))) {
            val g = CacheTagConfig.Aperture.geometry(b, n, 14)
            for (address <- Seq(b, b + BigInt(64).min(n - 1), b + n - 1)) {
                val tag = address >> g.tagLow
                val stored = tag & ((BigInt(1) << g.tagBits) - 1)
                val restored = (stored << g.tagLow) | (address & ((BigInt(1) << g.tagLow) - 1))
                restored shouldBe address
            }
        }
    }
    it should "reject invalid apertures and tag geometries" in {
        for ((base, bytes) <- Seq((BigInt(-64), BigInt(64)), (BigInt(1), BigInt(64)),
            (BigInt(0), BigInt(0)), ((BigInt(1) << 64) - 64, BigInt(128)))) {
            intercept[IllegalArgumentException] { CacheTagConfig.Aperture.geometry(base, bytes, 14) }
        }
        intercept[IllegalArgumentException] { CacheTagConfig.Aperture.geometry(0, 64, 64) }
    }
}
