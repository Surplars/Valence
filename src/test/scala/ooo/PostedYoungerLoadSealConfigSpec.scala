package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Constructor-only checks; actual nested instances are checked by the dedicated emitter audit. */
class PostedYoungerLoadSealConfigSpec extends AnyFunSuite {
    private val flag = "--posted-younger-load-seal-deferral"
    private def fields(p: Product): Map[String, Any] = p.productElementNames.zip(p.productIterator).toMap
    private def changes(before: Product, after: Product): Map[String, Any] =
        fields(after).filter { case (name, value) => fields(before)(name) != value }

    test("the explicit 69th option changes only the appended profile and core fields") {
        val off = NearTermAProfile.on
        val options = NearTermAProfile.onOptions :+ flag
        FpgaNextProfileOptions.validate(options)
        val on = FpgaNextConfig.fromOptions(options.toSet, defaultSelected = false)
        assert(options.size == 69 && options.dropRight(1) == NearTermAProfile.onOptions)
        assert(on.productArity == 90 && on.coreParams.productArity == 173)
        PlacedTimingProfileBridge.requireShape(on)
        assert(on.productElementName(88) == "triSpeedRawClockHandoff")
        assert(!on.triSpeedRawClockHandoff)
        assert(on.productElementName(89) == "postedYoungerLoadSealDeferral")
        assert(on.coreParams.productElementName(172) == "postedYoungerLoadSealDeferral")
        assert(on.copy(postedYoungerLoadSealDeferral = false) == off)
        assert(on.coreParams.copy(postedYoungerLoadSealDeferral = false) == off.coreParams)
        assert(changes(off, on) == Map("postedYoungerLoadSealDeferral" -> true))
        assert(changes(off.coreParams, on.coreParams) == Map("postedYoungerLoadSealDeferral" -> true))
        assert(on.name == off.name + "-posted-younger-load-seal-deferral")
        assert(on.cache == off.cache && on.ddr == off.ddr && on.storage == off.storage &&
            on.tags == off.tags && on.network == off.network &&
            on.floatingPointResources == off.floatingPointResources)
        assert(PostedBoardConfiguration.document(on.copy(postedYoungerLoadSealDeferral = false)) ==
            PostedBoardConfiguration.document(off))
        assert(on.productElementName(79) == off.productElementName(79) &&
            on.coreParams.productElementName(164) == off.coreParams.productElementName(164))
    }

    test("every retained preset and historical A view keeps the appended option false") {
        for (c <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.FetchCaptureCandidate,
                FpgaNextConfig.TriSpeedCandidate, FpgaNextConfig.ControlCandidate, FpgaNextConfig.Selected,
                FpgaNextConfig.RegisteredPmpCandidate, R3ReadLocalityProfile.off, R3ReadLocalityProfile.on,
                NearTermAProfile.rollback, NearTermAProfile.on)) {
            assert(!c.postedYoungerLoadSealDeferral && !c.coreParams.postedYoungerLoadSealDeferral)
            assert(PlacedTimingProfileBridge.historicalAFields(c).size == 88)
            assert(PlacedTimingProfileBridge.historicalAFields(c.coreParams).size == 172)
        }
        assert(!OooParams().postedYoungerLoadSealDeferral)
        assert(!BoardSocConfig.boardParams(BoardSocConfig.timingProfile).postedYoungerLoadSealDeferral)
    }

    test("board parameter forwarding preserves the complete off constructor") {
        val off = BoardSocConfig.boardParams("staged-fetch-turnover", postedStoreMerge = true)
        val on = BoardSocConfig.boardParams("staged-fetch-turnover", postedStoreMerge = true,
            postedYoungerLoadSealDeferral = true)
        assert(on == off.copy(postedYoungerLoadSealDeferral = true))
    }

    test("constructor legality requires posted stores staged addresses and no proof frontier") {
        val posted = OooParams(bufferedRamStores = true, machineSystem = true, pmpEntries = 8,
            virtualMemoryLevels = 3, speculativeRamBytes = 4096, postedStoreMerge = true,
            registeredMemoryAddress = true)
        assert(posted.copy(postedYoungerLoadSealDeferral = true).postedYoungerLoadSealDeferral)
        for (invalid <- Seq(posted.copy(postedStoreMerge = false), posted.copy(registeredMemoryAddress = false))) {
            val error = intercept[IllegalArgumentException] { invalid.copy(postedYoungerLoadSealDeferral = true) }
            assert(error.getMessage.contains("younger-load seal deferral requires"))
        }
        val frontier = FpgaNextConfig(postedStoreMerge = true, memoryProofFrontier = true,
            robEntries = Some(64), physicalRegs = Some(64), lsuEntries = 4,
            virtualRamLoadPrecheck = true, canonicalVirtualStoreOverlap = true,
            loadOrderOlderRetire = true, dataTranslationEntries = 16)
        val frontierCore = frontier.coreParams
        intercept[IllegalArgumentException] { frontier.copy(postedYoungerLoadSealDeferral = true) }
        val error = intercept[IllegalArgumentException] { frontierCore.copy(postedYoungerLoadSealDeferral = true) }
        assert(error.getMessage.contains("younger-load seal deferral requires"))
        intercept[IllegalArgumentException] { FpgaNextConfig(postedYoungerLoadSealDeferral = true) }
    }

    test("ordered public options reject duplicate unknown and valued Boolean spellings") {
        val base = NearTermAProfile.onOptions
        for (options <- Seq(base :+ flag, flag +: base, base.reverse :+ flag)) {
            FpgaNextProfileOptions.validate(options)
            assert(FpgaNextConfig.fromOptions(options.toSet, false) ==
                NearTermAProfile.on.copy(postedYoungerLoadSealDeferral = true))
        }
        for (invalid <- Seq(flag.dropRight(1), flag + "s", "--posted_younger_load_seal_deferral")) {
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(base :+ invalid) }
        }
        intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(base ++ Seq(flag, flag)) }
        for (value <- Seq("", "true", "false", "0", "1")) {
            val valued = flag + "=" + value
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(base :+ valued) }
            intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(base.toSet + valued, false) }
        }
    }
}
