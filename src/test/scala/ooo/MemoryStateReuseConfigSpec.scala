package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.{BoardSocConfig, FpgaNextConfig, FpgaStorageConfig, OooParams}

/** Pure constructor/CLI checks; no hardware elaboration or simulation. */
class MemoryStateReuseConfigSpec extends AnyFunSuite {
    private val tokenFlag = "--reconstruct-issue-token-index"
    private val addressFlag = "--shared-memory-address-state"

    test("issue-token index reconstruction is independently default off") {
        assert(!OooParams().reconstructIssueTokenIndex)
        assert(!FpgaStorageConfig.Registers.reconstructIssueTokenIndex && !FpgaStorageConfig.Registers.enabled)
        for (base <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected)) {
            assert(!base.reconstructIssueTokenIndex && !base.coreParams.reconstructIssueTokenIndex)
        }
        assert(!StorePrefetchLruVictimProfiles.profile(true).coreParams.reconstructIssueTokenIndex)
        for (selector <- Seq("--reference", "--candidate", "--selected")) {
            val off = FpgaNextConfig.fromOptions(Set(selector), defaultSelected = false)
            val on = FpgaNextConfig.fromOptions(Set(selector, tokenFlag), defaultSelected = false)
            assert(on == off.copy(reconstructIssueTokenIndex = true))
            assert(on.storage == off.storage.copy(reconstructIssueTokenIndex = true))
            assert(on.coreParams.copy(reconstructIssueTokenIndex = false) == off.coreParams)
            assert(on.name.replace("-reconstruct-issue-token-index", "") == off.name)
        }
    }

    test("production storage selector reaches the board without changing other fields") {
        val (remaining, storage) = FpgaStorageConfig.parseArgs(Array("out", "--compact-tags", tokenFlag))
        assert(remaining.toSeq == Seq("out", "--compact-tags"))
        assert(storage == FpgaStorageConfig(reconstructIssueTokenIndex = true) && storage.enabled)
        val off = BoardSocConfig.boardParams("staged-fetch-turnover")
        val on = BoardSocConfig.boardParams("staged-fetch-turnover", fpgaStorage = storage)
        assert(on.reconstructIssueTokenIndex && on.copy(reconstructIssueTokenIndex = false) == off)
        assert(storage.configure(OooParams()).copy(reconstructIssueTokenIndex = false) == OooParams())
    }

    test("shared memory addresses stay default off and compose with issue-token reconstruction") {
        assert(!OooParams().sharedMemoryAddressState)
        assert(!FpgaStorageConfig.Registers.sharedMemoryAddressState)
        for (base <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected)) {
            assert(!base.sharedMemoryAddressState && !base.coreParams.sharedMemoryAddressState)
        }
        assert(!StorePrefetchLruVictimProfiles.profile(true).coreParams.sharedMemoryAddressState)
        for (selector <- Seq("--reference", "--candidate", "--selected");
             reconstruct <- Seq(false, true); shared <- Seq(false, true)) {
            val flags = (if (reconstruct) Set(tokenFlag) else Set.empty[String]) ++
                (if (shared) Set(addressFlag) else Set.empty[String])
            val off = FpgaNextConfig.fromOptions(Set(selector), defaultSelected = false)
            val selected = FpgaNextConfig.fromOptions(Set(selector) ++ flags, defaultSelected = false)
            assert(selected == off.copy(reconstructIssueTokenIndex = reconstruct, sharedMemoryAddressState = shared))
            assert(selected.coreParams == off.coreParams.copy(
                reconstructIssueTokenIndex = reconstruct, sharedMemoryAddressState = shared))
            assert(selected.storage == off.storage.copy(
                reconstructIssueTokenIndex = reconstruct, sharedMemoryAddressState = shared))
            val (remaining, storage) = FpgaStorageConfig.parseArgs(Array("out") ++ flags.toSeq.sorted)
            assert(remaining.toSeq == Seq("out"))
            assert(storage.enabled == (reconstruct || shared))
            assert(storage.configure(OooParams()) == OooParams(
                reconstructIssueTokenIndex = reconstruct, sharedMemoryAddressState = shared))
        }
    }

    test("Boolean storage selectors reject duplicate and valued forms") {
        for (flag <- Seq(tokenFlag, addressFlag)) {
            intercept[IllegalArgumentException] { FpgaStorageConfig.parseArgs(Array(flag, flag)) }
        }
        for (flag <- Seq(tokenFlag, addressFlag); value <- Seq("true", "false", "1", "")) {
            intercept[IllegalArgumentException] { FpgaStorageConfig.parseArgs(Array(flag + "=" + value)) }
            intercept[IllegalArgumentException] {
                FpgaNextConfig.fromOptions(Set(flag + "=" + value), defaultSelected = false)
            }
        }
    }
}
