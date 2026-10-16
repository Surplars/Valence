package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}

/** Focused direct-responder fixture, with current repair core parameters.
  * Native board/PMP construction is separately bound by EarlyLoadDescriptorBoardGsimMain.
  */
object EarlyLoadPreparationBackendMain extends App {
    require(args.length == 1)
    val out = Paths.get(args(0)); require(!Files.exists(out))
    val profile = CombinedTimingRepairR1Profile.config(true)
    var inventory = Map.empty[String, Int]
    var actualArguments = Map.empty[String, Boolean]
    ChiselStage.emitCHIRRTLFile({
        val dut = new ReadyStoreQuery77BackendGsim(true, proofRows = 3,
            preselectRedirectTokenMatches = false, proofControlInputs = true,
            shadowEarlyProofBind = true, proofBankQuiesceIntent = true, proofBankOwnerCleanup = true,
            factorPreparedStorePool = true, currentProfile = Some(profile),
            projectedRequestHead = true, registeredMemoryPreparationDescriptor = true,
            earlyLoadPreparationDescriptor = true)
        val b = dut.backend
        require(b.p == profile.coreParams && dut.profile == profile)
        require(profile.productArity == 96 && b.p.productArity == 179)
        require(b.registeredMemoryPreparationDescriptor && b.earlyLoadPreparationDescriptor &&
            b.preparationDescriptor.get.getWidth == 275 && b.preparationDescriptorValid.get.getWidth == 1)
        inventory = Map("physicalReads" -> b.physicalReads.length,
            "issuePayloadReads" -> b.issuePayloadReads.length, "descriptorPayloadBits" -> 275, "descriptorValidBits" -> 1)
        actualArguments = ReadyStoreQuery77BackendFactory.arguments(profile) ++ Map(
            "preselectRedirectTokenMatches" -> b.preselectRedirectTokenMatches,
            "shadowEarlyProofBind" -> b.shadowEarlyProofBind, "proofBankQuiesceIntent" -> b.proofBankQuiesceIntent,
            "proofBankOwnerCleanup" -> b.proofBankOwnerCleanup, "factorPreparedStorePool" -> b.factorPreparedStorePool,
            "projectedRequestHead" -> b.projectedRequestHead,
            "registeredMemoryPreparationDescriptor" -> b.registeredMemoryPreparationDescriptor,
            "earlyLoadPreparationDescriptor" -> b.earlyLoadPreparationDescriptor,
            "backendNaturalAlignedPmp" -> b.backendNaturalAlignedPmp)
        dut
    }, Array("--target-dir", out.toString))
    Files.writeString(out.resolve("actual-core.json"), PostedBoardConfiguration.json(profile.coreParams) + "\n")
    Files.writeString(out.resolve("actual-profile.json"), PostedBoardConfiguration.json(profile) + "\n")
    Files.writeString(out.resolve("actual-backend-arguments.json"), PostedBoardConfiguration.json(actualArguments) + "\n")
    Files.writeString(out.resolve("read-inventory.json"), PostedBoardConfiguration.json(inventory) + "\n")
}
