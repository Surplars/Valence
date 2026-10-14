package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Pure constructor/metadata checks only. No ChiselStage, DUT elaboration or simulation. */
class ResidentMemoryIntegrationConfigSpec extends AnyFunSuite {
    private val profile = ResidentMemoryIntegrationProfile
    private def fields(p: Product): Map[String, Any] = p.productElementNames.zip(p.productIterator).toMap

    test("Young69 plus one explicit resident option preserves every other current parameter") {
        assert(profile.offOptions.size == 69 && profile.onOptions.size == 70)
        assert(profile.on.copy(residentMemoryPayloadReuse = false) == profile.off)
        assert(profile.on.coreParams.copy(residentMemoryPayloadReuse = false) == profile.off.coreParams)
        assert(profile.on.productArity == 92 && profile.on.coreParams.productArity == 175)
        assert(profile.on.postedYoungerLoadSealDeferral && !profile.on.heldAluIssueForwarding &&
            !profile.on.triSpeedRawClockHandoff)
        for (c <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected,
                NearTermAProfile.on, MacRawHandoffEntry.on, HeldAluIntegrationProfile.on,
                YoungLoadSealSourceBridge.candidate(profile.offOptions))) {
            assert(!c.residentMemoryPayloadReuse && !c.coreParams.residentMemoryPayloadReuse)
        }
        assert(!OooParams().residentMemoryPayloadReuse)
    }

    test("boardParams enables resident only after requested LVT storage has been configured") {
        def direct(enabled: Boolean, storage: FpgaStorageConfig): OooParams = BoardSocConfig.boardParams(
            BoardSocConfig.memoryCapacityProfile, fpgaStorage = storage, residentMemoryPayloadReuse = enabled)
        val storage = FpgaStorageConfig(lvtPhysicalRegisterFile = true)
        val off = direct(false, storage)
        val on = direct(true, storage)
        assert(on.lvtPhysicalRegisterFile && on.residentMemoryPayloadReuse)
        assert(on.copy(residentMemoryPayloadReuse = false) == off)
        // The public coreParams route must reach the same final-configuration boundary.
        assert(profile.on.coreParams.lvtPhysicalRegisterFile && profile.on.coreParams.residentMemoryPayloadReuse)
        intercept[IllegalArgumentException] { direct(true, FpgaStorageConfig.Registers) }
    }

    test("each resident topology predicate remains enforced without a profile exception") {
        val p = profile.on.coreParams
        val mutations: Seq[() => OooParams] = Seq(
            () => p.copy(robEntries = 32), () => p.copy(physicalRegs = 64), () => p.copy(tagBits = 32),
            () => p.copy(renameWidth = 1), () => p.copy(completionWidth = 1), () => p.copy(commitWidth = 1),
            () => p.copy(memoryEntries = 2), () => p.copy(registeredMemoryAddress = false),
            () => p.copy(parallelMemoryPreparation = false), () => p.copy(parallelMemoryPayload = false),
            () => p.copy(compactMemoryOperandSelect = false), () => p.copy(parallelMemoryAddressSum = false),
            () => p.copy(lvtPhysicalRegisterFile = false), () => p.copy(ownerLocalOperandReady = false),
            () => p.copy(registeredIssueExecute = false), () => p.copy(moveAlias = true),
            () => p.copy(loadCompletionBypass = true), () => p.copy(mulWordPreviewBypass = true),
            () => p.copy(memoryProofFrontier = true), () => p.copy(fastBufferedStoreRetire = true),
            () => p.copy(fastHeadLoadRetire = true))
        mutations.foreach(change => intercept[IllegalArgumentException] { change() })
        intercept[IllegalArgumentException] { OooParams(residentMemoryPayloadReuse = true) }
    }

    test("exact ordered option and redundant constructor arguments fail closed") {
        val flag = profile.flag
        intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(profile.onOptions :+ flag) }
        for (bad <- Seq("--resident", "--resident-memory-payload", "--resident_memory_payload_reuse") ++
                Seq("", "true", "false", "0", "1").map(flag + "=" + _)) {
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(profile.offOptions :+ bad) }
            intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(profile.offOptions.toSet + bad, false) }
        }
        intercept[IllegalArgumentException] { profile.requireSide("on", profile.onOptions.reverse, profile.on) }
        ResidentMemoryIntegrationActualAudit.requireArgument(profile.on, true)
        ResidentMemoryIntegrationActualAudit.requireArgument(profile.off, false)
        intercept[IllegalArgumentException] { ResidentMemoryIntegrationActualAudit.requireArgument(profile.on, false) }
        intercept[IllegalArgumentException] { ResidentMemoryIntegrationActualAudit.requireArgument(profile.off, true) }
    }

    test("measured Young projection preserves its true field and rejects false-tail type or order drift") {
        val p = profile.off.coreParams
        val names = p.productElementNames.toSeq
        val values = fields(p)
        val old = profile.historicalFields(p)
        assert(old.size == 173 && old("postedYoungerLoadSealDeferral") == true)
        assert(profile.historicalFields(profile.off).size == 89)
        for (bad <- Seq[Any](true, 0, 1, "false", null)) {
            intercept[IllegalArgumentException] {
                profile.historicalFields("core", names, values.updated(profile.field, bad))
            }
        }
        for (bad <- Seq(names.reverse, names.dropRight(1), names :+ "unknown",
                names.dropRight(2) ++ Seq(profile.field, "heldAluIssueForwarding"),
                names.dropRight(1) :+ "heldAluIssueForwarding")) {
            intercept[IllegalArgumentException] { profile.historicalFields("core", bad, values) }
        }
        intercept[IllegalArgumentException] { profile.historicalFields("core", names, values - "tagBits") }
        intercept[IllegalArgumentException] { profile.historicalFields("core", names, values + ("unknown" -> false)) }
        intercept[IllegalArgumentException] { profile.historicalDocument(profile.on) }
        intercept[IllegalArgumentException] { YoungLoadSealSourceBridge.historicalFields(profile.on) }
        intercept[IllegalArgumentException] { HeldAluIntegrationProfile.historicalAFields(profile.on) }
        intercept[IllegalArgumentException] { PlacedTimingProfileBridge.historicalAFields(profile.on) }
    }

    test("complete historical comparison rejects old scalar Boolean-type and nested-resource changes") {
        val document = profile.historicalDocument(profile.off)
        val core = profile.historicalFields(profile.off.coreParams)
        for ((name, value) <- Seq("tagBits" -> 32, "postedYoungerLoadSealDeferral" -> 1,
                "floatingPoint" -> "changed nested product")) {
            intercept[IllegalArgumentException] {
                profile.requireHistoricalDocument(document.updated("core", core.updated(name, value)))
            }
        }
        intercept[IllegalArgumentException] { profile.requireHistoricalDocument(document - "cache") }
        intercept[IllegalArgumentException] { profile.requireHistoricalDocument(document + ("unknown" -> false)) }
    }
}
