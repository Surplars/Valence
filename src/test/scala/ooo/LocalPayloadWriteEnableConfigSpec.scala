package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class LocalPayloadWriteEnableConfigSpec extends AnyFunSuite {
    test("payload write-enable option is independent and defaults off") {
        assert(!DdrBridgeConfig.Legacy.localPayloadWriteEnable)
        assert(!DdrBridgeConfig.ReadOverlap4.localPayloadWriteEnable)
        for (base <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected)) {
            assert(!base.localPayloadWriteEnable && !base.ddr.localPayloadWriteEnable)
            val on = base.copy(localPayloadWriteEnable = true)
            assert(on.copy(localPayloadWriteEnable = false) == base)
            assert(on.ddr == base.ddr.copy(localPayloadWriteEnable = true))
            assert(on.coreParams == base.coreParams && on.cache == base.cache && on.storage == base.storage)
            assert(on.network == base.network && on.name == base.name + "-local-payload-write-enable")
        }
        val parsed = FpgaNextConfig.fromOptions(Set("--selected", "--local-payload-write-enable"), true)
        assert(parsed == FpgaNextConfig.Selected.copy(localPayloadWriteEnable = true))
        FpgaNextProfileOptions.validate(Seq("--selected", "--local-payload-write-enable"))
        intercept[IllegalArgumentException] {
            FpgaNextConfig.fromOptions(Set("--local-payload-write-enable=false"), true)
        }
        intercept[IllegalArgumentException] {
            FpgaNextProfileOptions.validate(Seq("--local-payload-write-enable", "--local-payload-write-enable"))
        }
    }
}
