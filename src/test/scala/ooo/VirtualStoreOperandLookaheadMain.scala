package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo._

object VirtualStoreOperandLookaheadProfile {
    val config = CombinedTimingRepairR1Profile.config(true)
    def construct(enabled: Boolean): FpgaNextSocTop = new FpgaNextSocTop(
        config = config, debug = CombinedTimingPmpR1Profile.debug,
        bscanChain = CombinedTimingPmpR1Profile.bscanChain,
        preselectRedirectTokenMatches = false, sharedTwoWordFetchPmp = true,
        disjointEvictionStoreOverlap = true, projectedRequestHead = true, factorPreparedStorePool = true,
        proofBankControlDecoupling = true, registerNextLineDecision = true,
        registeredMemoryPreparationDescriptor = true, backendNaturalAlignedPmp = true,
        virtualStoreOperandLookahead = enabled)
    def compareBaseline(actual: Map[String, Any], reference: String): Unit = {
        require(CombinedTimingRepairR1Audit.json(actual) == ujson.read(Files.readString(Paths.get(reference))),
            "all existing actual profile/native fields must equal production repair-ON")
        require(!config.translatedResponseEmptyFlow && !config.frozenStoreCheckedFlow)
    }
}
object VirtualStoreOperandLookaheadBackendMain extends App {
    require(args.length == 2 && Set("off", "on").contains(args(1)))
    val out = Paths.get(args(0)); require(!Files.exists(out))
    val enabled = args(1) == "on"
    val profile = VirtualStoreOperandLookaheadProfile.config
    var inventory = Map.empty[String, Int]
    ChiselStage.emitCHIRRTLFile({
        val dut = new ReadyStoreQuery77BackendGsim(true, proofRows = 3,
            preselectRedirectTokenMatches = false, proofControlInputs = true,
            shadowEarlyProofBind = true, proofBankQuiesceIntent = true, proofBankOwnerCleanup = true,
            factorPreparedStorePool = true, currentProfile = Some(profile), projectedRequestHead = true,
            registeredMemoryPreparationDescriptor = true, backendNaturalAlignedPmp = true,
            virtualStoreOperandLookahead = enabled)
        val b = dut.backend
        require(b.p == profile.coreParams && dut.profile == profile)
        require(b.virtualStoreOperandLookahead == enabled && b.registeredMemoryPreparationDescriptor &&
            b.backendNaturalAlignedPmp && b.factorPreparedStorePool && b.projectedRequestHead)
        inventory = Map("physicalReads" -> b.physicalReads.length, "issuePayloadReads" -> b.issuePayloadReads.length)
        dut
    }, Array("--target-dir", out.toString))
    Files.writeString(out.resolve("actual-core.json"), PostedBoardConfiguration.json(profile.coreParams) + "\n")
    Files.writeString(out.resolve("actual-profile.json"), PostedBoardConfiguration.json(profile) + "\n")
    Files.writeString(out.resolve("read-inventory.json"), PostedBoardConfiguration.json(inventory) + "\n")
    Files.writeString(out.resolve("candidate.json"), ujson.Obj("virtualStoreOperandLookahead" -> enabled,
        "earlyQ" -> false, "l2" -> false).render(indent = 2) + "\n")
}
object VirtualStoreOperandLookaheadNativeMain extends App {
    require(args.length == 3 && Set("off", "on").contains(args(1)))
    val out = Paths.get(args(0)); require(!Files.exists(out))
    val enabled = args(1) == "on"
    var built: Option[FpgaNextSocTop] = None
    val fir = ChiselStage.emitCHIRRTL {
        val dut = VirtualStoreOperandLookaheadProfile.construct(enabled); built = Some(dut); dut
    }
    val dut = built.get
    val actual = CombinedTimingRepairR1Audit.capture(dut, VirtualStoreOperandLookaheadProfile.config, true)
    VirtualStoreOperandLookaheadProfile.compareBaseline(actual, args(2))
    require(dut.virtualStoreOperandLookahead == enabled && dut.board.virtualStoreOperandLookahead == enabled &&
        dut.board.platform.virtualStoreOperandLookahead == enabled &&
        dut.board.platform.core.virtualStoreOperandLookahead == enabled &&
        dut.board.platform.core.core.virtualStoreOperandLookahead == enabled &&
        dut.board.platform.core.core.core.virtualStoreOperandLookahead == enabled &&
        dut.board.platform.core.core.core.backend.virtualStoreOperandLookahead == enabled)
    CombinedTimingRepairR1Emission.write(out, "FpgaNextSocTop", fir, actual, true)
    Files.writeString(out.resolve("candidate.json"), ujson.Obj("virtualStoreOperandLookahead" -> enabled,
        "earlyQ" -> false, "l2" -> false).render(indent = 2) + "\n")
}
object VirtualStoreOperandLookaheadBoardGsimMain extends App {
    require(args.length == 3 && Set("off", "on").contains(args(1)))
    val out = Paths.get(args(0)); require(!Files.exists(out))
    val enabled = args(1) == "on"
    val c = VirtualStoreOperandLookaheadProfile.config
    var built: Option[BoardSocGsim] = None
    val fir = ChiselStage.emitCHIRRTL {
        val dut = FpgaNextBoardGsim.build(c, verifyConfiguration = true, sharedTwoWordFetchPmp = true,
            disjointEvictionStoreOverlap = true, proofBankControlDecoupling = true,
            projectedRequestHead = true, factorPreparedStorePool = true, combinedTimingR1Audit = true,
            registerNextLineDecision = true, registeredMemoryPreparationDescriptor = true,
            backendNaturalAlignedPmp = true, virtualStoreOperandLookahead = enabled)
        built = Some(dut); dut
    }
    val actual = CombinedTimingRepairR1Audit.capturePlatform(built.get.observedPlatform, c, true)
    val actualJson = CombinedTimingRepairR1Audit.json(actual)
    val reference = ujson.read(Files.readString(Paths.get(args(2))))
    Seq("core", "profile", "fieldOrder", "geometry", "clockHz", "featureFlags", "counts",
        "pmpDecisionObservation", "descriptorObservation").foreach { key =>
        require(actualJson(key) == reference(key), s"GSIM/native mismatch: $key")
    }
    require(built.get.virtualStoreOperandLookahead == enabled &&
        built.get.observedPlatform.virtualStoreOperandLookahead == enabled &&
        built.get.observedPlatform.core.virtualStoreOperandLookahead == enabled &&
        built.get.observedPlatform.core.core.virtualStoreOperandLookahead == enabled &&
        built.get.observedPlatform.core.core.core.virtualStoreOperandLookahead == enabled &&
        built.get.observedPlatform.core.core.core.backend.virtualStoreOperandLookahead == enabled)
    CombinedTimingRepairR1Emission.write(out, "BoardSocGsim", fir, actual, true)
    CombinedTimingRepairR1FabricAudit.write(out.toString)
    Files.writeString(out.resolve("actual-combined-timing-repair-gsim.json"), actualJson.render(indent = 2) + "\n")
    Files.writeString(out.resolve("candidate.json"), ujson.Obj("virtualStoreOperandLookahead" -> enabled,
        "earlyQ" -> false, "l2" -> false).render(indent = 2) + "\n")
}

object VirtualStoreOperandLookaheadConfigMain extends App {
    val p = VirtualStoreOperandLookaheadProfile.config.coreParams
    VirtualStoreOperandLookaheadContract.requireSupported(p, true, true, true)
    VirtualStoreOperandLookaheadContract.requireSupported(OooParams(), false, false, false)
    var rejected = 0
    def reject(body: => Unit): Unit = {
        var denied = false
        try { body } catch { case _: IllegalArgumentException => denied = true }
        require(denied, "unsupported operand-lookahead constructor accepted")
        rejected += 1
    }
    reject { VirtualStoreOperandLookaheadContract.requireSupported(p, true, false, true) }
    reject { VirtualStoreOperandLookaheadContract.requireSupported(p, true, true, false) }
    reject { VirtualStoreOperandLookaheadContract.requireSupported(OooParams(), true, true, true) }
    val unsupported = Seq[() => OooParams](
        () => p.copy(parallelMemoryPreparation = false), () => p.copy(registeredMemoryAddress = false),
        () => p.copy(residentMemoryPayloadReuse = false), () => p.copy(preparedStoreLookahead = false),
        () => p.copy(postedPreparationPriority = true), () => p.copy(registeredIssueHeadMask = false),
        () => p.copy(bankedIssuePayload = false), () => p.copy(unconditionalMemoryPayloadCapture = false),
        () => p.copy(virtualMemoryLevels = 0), () => p.copy(fastBufferedStoreRetire = true),
        () => p.copy(fastHeadLoadRetire = true), () => p.copy(memoryProofFrontier = true),
        () => p.copy(translatedResponseEmptyFlow = true), () => p.copy(frozenStoreCheckedFlow = true),
        () => p.copy(physicalRegs = 64), () => p.copy(tagBits = 32), () => p.copy(memoryEntries = 3))
    unsupported.foreach(change => reject {
        VirtualStoreOperandLookaheadContract.requireSupported(change(), true, true, true)
    })
    println(s"VIRTUAL_OPERAND_CONFIG_PASS rejected=$rejected supported=true default_off=true")
}
