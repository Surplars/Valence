package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Actual 50cb backend profile, no full board or CPU model emission. */
object BankedStoreDataBackendMain extends App {
    require(args.length == 2 && Set("off", "on").contains(args(1)))
    val out = Paths.get(args(0)); require(!Files.exists(out))
    val enabled = args(1) == "on"
    val profile = CombinedTimingRepairR1Profile.config(true)
    var inventory = Map.empty[String, Int]
    ChiselStage.emitCHIRRTLFile({
        val dut = new ReadyStoreQuery77BackendGsim(true, proofRows = 3,
            preselectRedirectTokenMatches = false, proofControlInputs = true,
            shadowEarlyProofBind = true, proofBankQuiesceIntent = true, proofBankOwnerCleanup = true,
            factorPreparedStorePool = true, currentProfile = Some(profile), projectedRequestHead = true,
            registeredMemoryPreparationDescriptor = true, backendNaturalAlignedPmp = true,
            bankedStoreData = enabled)
        val b = dut.backend
        require(b.p == profile.coreParams && dut.profile == profile)
        require(b.bankedStoreData == enabled && b.registeredMemoryPreparationDescriptor &&
            b.backendNaturalAlignedPmp && b.factorPreparedStorePool && b.projectedRequestHead)
        require(!profile.translatedResponseEmptyFlow && !profile.frozenStoreCheckedFlow)
        inventory = Map("physicalReads" -> b.physicalReads.length, "issuePayloadReads" -> b.issuePayloadReads.length,
            "storeDataFunctionalReadPorts" -> (if (enabled) b.storeDataRam.get.io.address.length else 2))
        dut
    }, Array("--target-dir", out.toString))
    Files.writeString(out.resolve("actual-core.json"), PostedBoardConfiguration.json(profile.coreParams) + "\n")
    Files.writeString(out.resolve("actual-profile.json"), PostedBoardConfiguration.json(profile) + "\n")
    Files.writeString(out.resolve("read-inventory.json"), PostedBoardConfiguration.json(inventory) + "\n")
    Files.writeString(out.resolve("candidate.json"), ujson.Obj("bankedStoreData" -> enabled,
        "earlyQ" -> false, "l2" -> false, "virtualStoreOperandLookahead" -> false).render(indent = 2) + "\n")
}
