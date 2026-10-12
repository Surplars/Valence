package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class ZeroCycleCleanupConfigSpec extends AnyFunSuite {
    test("two named default-off fields preserve all prior products and geometry") {
        val off = FpgaNextConfig.Selected
        assert(off.productArity == 68 && off.coreParams.productArity == 157 &&
            off.ddr.productArity == 8 && off.cache.productArity == 22)
        assert(!off.directRegisteredExecutionOperands && !off.coreParams.directRegisteredExecutionOperands &&
            !off.localPayloadWriteEnable && !off.ddr.localPayloadWriteEnable)
        val on = FpgaNextConfig.fromOptions(Set("--selected", "--direct-registered-execution-operands",
            "--local-payload-write-enable"), defaultSelected = false)
        assert(on.directRegisteredExecutionOperands && on.coreParams.directRegisteredExecutionOperands &&
            on.localPayloadWriteEnable && on.ddr.localPayloadWriteEnable)
        assert(on.copy(directRegisteredExecutionOperands = false, localPayloadWriteEnable = false) == off)
        assert(on.coreParams.copy(directRegisteredExecutionOperands = false) == off.coreParams)
        assert(on.ddr.copy(localPayloadWriteEnable = false) == off.ddr)
        assert(on.cache == off.cache && on.storage == off.storage && on.network == off.network)
        assert(on.coreParams.issueWidth == 2 && on.ddr.maxOutstanding == 4 &&
            on.ddr.maxOutstandingWrites == 2 && on.ddr.maxBurstBeats == 16)
    }
    test("both exact Boolean option names fail closed on duplicate or valued forms") {
        for (flag <- Seq("--direct-registered-execution-operands", "--local-payload-write-enable")) {
            FpgaNextProfileOptions.validate(Seq("--selected", flag))
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(Seq(flag, flag)) }
            for (value <- Seq("true", "false", "0", "1")) {
                intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(Seq(flag + "=" + value)) }
                intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(Set(flag + "=" + value), true) }
            }
        }
        intercept[IllegalArgumentException] { OooParams(directRegisteredExecutionOperands = true) }
    }
}
