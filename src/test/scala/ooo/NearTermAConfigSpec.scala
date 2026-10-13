package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class NearTermAConfigSpec extends AnyFunSuite {
    test("exact64 rollback projects only four explicitly false fields and retains every old value") {
        val off = NearTermAProfile.rollback
        val on = NearTermAProfile.on
        assert(NearTermAProfile.originalFields(off).size == 84)
        assert(NearTermAProfile.originalFields(off.coreParams).size == 168)
        intercept[IllegalArgumentException] { NearTermAProfile.originalFields(on) }
        intercept[IllegalArgumentException] { NearTermAProfile.originalFields(on.coreParams) }
        for (c <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected, off)) {
            NearTermAProfile.originalFields(c)
            NearTermAProfile.originalFields(c.coreParams)
        }
    }
    test("new switches retain constructor preconditions and exact public option syntax") {
        intercept[IllegalArgumentException] { OooParams(factorCheckedNextAllowed = true) }
        intercept[IllegalArgumentException] { OooParams(localTaggedResponseReady = true) }
        intercept[IllegalArgumentException] { OooParams(fetchAcceptedPrefixValidation = true) }
        intercept[IllegalArgumentException] { OooParams(alignedFetchSinglePage = true) }
        for (flag <- NearTermAProfile.additions) {
            intercept[IllegalArgumentException] {
                FpgaNextProfileOptions.validate(NearTermAProfile.onOptions :+ flag)
            }
            for (value <- Seq("", "true", "false", "0", "1")) {
                intercept[IllegalArgumentException] {
                    FpgaNextProfileOptions.validate(NearTermAProfile.rollbackOptions :+ (flag + "=" + value))
                }
                intercept[IllegalArgumentException] {
                    FpgaNextConfig.fromOptions(NearTermAProfile.rollbackOptions.toSet + (flag + "=" + value), false)
                }
            }
        }
    }
}
