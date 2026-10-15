package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Isolated constructor identity; native/export defaults and qualified77 stay frozen. */
object ThreeProofRowCandidateProfile {
    val identity = "qualified77-three-proof-rows-two-credits-r1"
    val baseline = ReadyStoreQuery77Profile.on
    val candidate = baseline.copy(pendingVirtualStoreProofSlots = 3)
    require(candidate.coreParams == baseline.coreParams.copy(pendingVirtualStoreProofSlots = 3))
    require(candidate.copy(pendingVirtualStoreProofSlots = 2) == baseline)
    require(candidate.pendingStoreEarlyLoadCredits == 2 && candidate.coreParams.memoryEntries == 4)
    require(candidate.cache == baseline.cache && candidate.storage == baseline.storage &&
        candidate.ddr == baseline.ddr && candidate.network == baseline.network)
    require(candidate.coreParams.pendingReadyStoreQuery && candidate.coreParams.registeredPendingStoreQuery)
}

object ThreeProofRowCandidateConfigMain extends App {
    val p = ThreeProofRowCandidateProfile
    var rejected = 0
    def reject(body: => Unit): Unit = {
        var failed = false
        try { body } catch { case _: IllegalArgumentException => failed = true }
        require(failed)
        rejected += 1
    }
    for (rows <- Seq(0, 4)) {
        reject { p.candidate.copy(pendingVirtualStoreProofSlots = rows) }
        reject { p.candidate.coreParams.copy(pendingVirtualStoreProofSlots = rows) }
    }
    for (credits <- Seq(1, 3)) {
        reject { p.candidate.copy(pendingStoreEarlyLoadCredits = credits) }
        reject { p.candidate.coreParams.copy(pendingStoreEarlyLoadCredits = credits) }
    }
    reject { p.candidate.copy(pendingReadyStoreQuery = false) }
    reject { p.candidate.coreParams.copy(pendingReadyStoreQuery = false) }
    reject { p.candidate.copy(registeredPendingStoreQuery = false) }
    reject { p.candidate.coreParams.copy(registeredPendingStoreQuery = false) }
    reject { p.candidate.copy(pendingReadyStoreBypass = false) }
    reject { p.candidate.coreParams.copy(pendingReadyStoreBypass = false) }
    reject { p.candidate.copy(memoryPreparationHeadMask = false) }
    reject { p.candidate.coreParams.copy(memoryPreparationHeadMask = false) }
    reject { FpgaNextProfileOptions.validate(Seq("--pending-virtual-store-proof-slots=3")) }
    require(ReadyStoreQuery77Profile.on.pendingVirtualStoreProofSlots == 2)
    for (default <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected))
        require(default.pendingVirtualStoreProofSlots != 3)
    println(s"PASS_THREE_PROOF_ROW_CONFIG identity=${p.identity} rejected=$rejected")
}

class ThreeProofRowConstructorAudit extends Module {
    val profile = ThreeProofRowCandidateProfile.candidate
    val p = profile.coreParams
    val canonicalHandoff = profile.cache.independentDemandAdmission && p.canonicalVirtualStoreOverlap
    val registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent
    val retirementSlotIdentity = p.retirementSlotIdentity
    require(canonicalHandoff && registerCanonicalStoreEvent && retirementSlotIdentity)
    val backend = Module(new IntegerBackend(p, canonicalHandoff = canonicalHandoff,
        registerCanonicalStoreEvent = registerCanonicalStoreEvent, retirementSlotIdentity = retirementSlotIdentity))
    val io = IO(chiselTypeOf(backend.io))
    io <> backend.io
    require(backend.p == profile.coreParams)
    require(backend.pendingStoreProof.get.state.length == 3)
    require(backend.pendingStoreCredit.get.state.length == 2)
    require(backend.proofFrontier.isEmpty && backend.p.memoryEntries == 4)
}

object ThreeProofRowConstructorAuditMain extends App {
    require(args.length == 1 && !Files.exists(Paths.get(args(0))), "fresh output required")
    var actualCore: Option[OooParams] = None
    var actualArguments: Option[Map[String, Boolean]] = None
    ChiselStage.emitCHIRRTLFile({
        val wrapper = new ThreeProofRowConstructorAudit
        actualCore = Some(wrapper.backend.p)
        actualArguments = Some(Map(
            "canonicalHandoff" -> wrapper.canonicalHandoff,
            "registerCanonicalStoreEvent" -> wrapper.registerCanonicalStoreEvent,
            "retirementSlotIdentity" -> wrapper.retirementSlotIdentity))
        wrapper
    }, Array("--target-dir", args(0)))
    require(actualCore.nonEmpty && actualArguments.nonEmpty)
    require(actualCore.get == ThreeProofRowCandidateProfile.candidate.coreParams)
    require(actualArguments.get.values.forall(identity))
    Files.writeString(Paths.get(args(0), "actual-core.json"),
        PostedBoardConfiguration.json(actualCore.get) + "\n")
    Files.writeString(Paths.get(args(0), "actual-backend-arguments.json"),
        ujson.Obj.from(actualArguments.get.map { case (name, value) => name -> ujson.Bool(value) }).render() + "\n")
}
