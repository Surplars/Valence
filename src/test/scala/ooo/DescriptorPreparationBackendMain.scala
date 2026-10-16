package ooo
import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
object DescriptorPreparationBackendMain extends App {
    require(args.length == 2 && Set("baseline", "descriptor").contains(args(1)))
    val out = Paths.get(args(0)); require(!Files.exists(out))
    val profile = CombinedTimingR1Profile.config(true)
    val descriptor = args(1) == "descriptor"
    var inventory = Map.empty[String, Int]
    var actualArguments = Map.empty[String, Boolean]
    ChiselStage.emitCHIRRTLFile({
        val dut = new ReadyStoreQuery77BackendGsim(true, proofRows = 3,
            preselectRedirectTokenMatches = false, proofControlInputs = true,
            shadowEarlyProofBind = true, proofBankQuiesceIntent = true, proofBankOwnerCleanup = true,
            factorPreparedStorePool = true, currentProfile = Some(profile),
            projectedRequestHead = true, registeredMemoryPreparationDescriptor = descriptor)
        val b = dut.backend
        require(b.p == profile.coreParams && dut.profile == profile)
        require(profile.productArity == 96 && b.p.productArity == 179)
        require(!b.preselectRedirectTokenMatches && b.shadowEarlyProofBind && b.proofBankQuiesceIntent &&
            b.proofBankOwnerCleanup && b.factorPreparedStorePool && b.projectedRequestHead &&
            b.registeredMemoryPreparationDescriptor == descriptor && b.p.unconditionalMemoryPayloadCapture)
        inventory = Map("physicalReads" -> b.physicalReads.length, "issuePayloadReads" -> b.issuePayloadReads.length)
        actualArguments = ReadyStoreQuery77BackendFactory.arguments(profile) ++ Map(
            "preselectRedirectTokenMatches" -> b.preselectRedirectTokenMatches,
            "shadowEarlyProofBind" -> b.shadowEarlyProofBind, "proofBankQuiesceIntent" -> b.proofBankQuiesceIntent,
            "proofBankOwnerCleanup" -> b.proofBankOwnerCleanup, "factorPreparedStorePool" -> b.factorPreparedStorePool,
            "projectedRequestHead" -> b.projectedRequestHead, "registeredMemoryPreparationDescriptor" -> b.registeredMemoryPreparationDescriptor)
        dut
    }, Array("--target-dir", out.toString))
    Files.writeString(out.resolve("actual-core.json"), PostedBoardConfiguration.json(profile.coreParams) + "\n")
    Files.writeString(out.resolve("actual-profile.json"), PostedBoardConfiguration.json(profile) + "\n")
    Files.writeString(out.resolve("actual-backend-arguments.json"), PostedBoardConfiguration.json(actualArguments) + "\n")
    Files.writeString(out.resolve("read-inventory.json"), PostedBoardConfiguration.json(inventory) + "\n")
}
