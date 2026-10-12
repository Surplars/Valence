package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class Lane1OwnerMatchConfigSpec extends AnyFunSuite {
    private val base = BoardSocConfig.timingParams("staged-load-issue").copy(
        robEntries = 16, physicalRegs = 48, tagBits = 64)

    test("owner sharing stays absent from every generic preset") {
        assert(!OooParams().sharedLane1OwnerMatch)
        for (config <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected)) {
            assert(!config.sharedLane1OwnerMatch && !config.coreParams.sharedLane1OwnerMatch)
            val enabled = config.copy(sharedLane1OwnerMatch = true)
            assert(enabled.coreParams.sharedLane1OwnerMatch)
            assert(enabled.coreParams.copy(sharedLane1OwnerMatch = false) == config.coreParams)
        }
        val off = FpgaNextConfig.fromOptions(Set("--selected"), defaultSelected = false)
        val on = FpgaNextConfig.fromOptions(Set("--selected", "--shared-lane1-owner-match"), defaultSelected = false)
        assert(on.sharedLane1OwnerMatch && on.coreParams.sharedLane1OwnerMatch)
        assert(on.copy(sharedLane1OwnerMatch = false) == off)
    }

    test("only raw registered two-lane full64 topology may enable sharing") {
        assert(base.copy(sharedLane1OwnerMatch = true).sharedLane1OwnerMatch)
        val invalid = Seq(
            () => base.copy(sharedLane1OwnerMatch = true, registeredIssueExecute = false),
            () => base.copy(sharedLane1OwnerMatch = true, parallelIssuePayload = false),
            () => base.copy(sharedLane1OwnerMatch = true, completionWidth = 1),
            () => base.copy(sharedLane1OwnerMatch = true, completionWidth = 3),
            () => base.copy(sharedLane1OwnerMatch = true, tagBits = 63),
            () => base.copy(sharedLane1OwnerMatch = true, tagBits = 65))
        for (construct <- invalid) {
            val error = intercept[IllegalArgumentException] { construct() }
            assert(error.getMessage.contains("shared lane-1 ownership requires"))
        }
    }

    test("owner-sharing CLI rejects repeated and valued options") {
        val flag = "--shared-lane1-owner-match"
        FpgaNextProfileOptions.validate(Seq(flag))
        intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(Seq(flag, flag)) }
        for (value <- Seq("true", "false", "0", "1")) {
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(Seq(flag + "=" + value)) }
            intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(Set(flag + "=" + value), true) }
        }
    }
}
