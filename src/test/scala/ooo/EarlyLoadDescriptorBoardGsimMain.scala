package ooo

import _root_.circt.stage.ChiselStage
import chisel3.experimental.BaseModule
import java.nio.file.{Files, Path, Paths}
import soc.core.ooo.{MemoryPreparationDescriptorSelector, PreparationSourceLifetimeCheck}

/** Test-only observations of the new constructor flag, independent of the requested argument. */
object EarlyLoadDescriptorActualAudit {
    private def descendants(m: BaseModule): Seq[BaseModule] = {
        val children = classOf[BaseModule].getMethod("getIds").invoke(m)
            .asInstanceOf[scala.collection.Iterable[_]].collect { case x: BaseModule => x }.toSeq
        m +: children.flatMap(descendants)
    }
    private def matchingBoard(dut: BoardSocGsim): MatchingManagedBoard = {
        val fields = dut.getClass.getDeclaredFields.filter(_.getType == classOf[MatchingManagedBoard])
        require(fields.length == 1, "actual matching board field missing or ambiguous")
        fields.head.setAccessible(true)
        fields.head.get(dut).asInstanceOf[MatchingManagedBoard]
    }
    def capture(dut: BoardSocGsim, enabled: Boolean): ujson.Value = {
        val board = matchingBoard(dut)
        val p = dut.observedPlatform
        require(board.platform eq p, "observed platform is not the constructed matching board")
        val backend = p.core.core.core.backend
        val flags = Map(
            "boardSocGsim" -> dut.earlyLoadPreparationDescriptor,
            "matchingManagedBoard" -> board.earlyLoadPreparationDescriptor,
            "machinePlatform" -> p.earlyLoadPreparationDescriptor,
            "mappedMachineCore" -> p.core.earlyLoadPreparationDescriptor,
            "machineCore" -> p.core.core.earlyLoadPreparationDescriptor,
            "integerCore" -> p.core.core.core.earlyLoadPreparationDescriptor,
            "integerBackend" -> backend.earlyLoadPreparationDescriptor
        )
        flags.foreach { case (name, actual) => require(actual == enabled, s"actual early-load flag mismatch: $name") }
        val modules = descendants(backend).distinct
        val selectors = modules.collect { case x: MemoryPreparationDescriptorSelector => x }
        val lifetime = modules.collect { case x: PreparationSourceLifetimeCheck => x }
        require(selectors.size == 1 && selectors.head.earlyLoads == enabled)
        require(selectors.head.io.waitingLoads.nonEmpty == enabled)
        val waitingMaskBits: Int = selectors.head.io.waitingLoads.map(_.getWidth).getOrElse(0)
        require(waitingMaskBits == (if (enabled) 16 else 0))
        require(lifetime.size == 3, "descriptor/fresh/resident source lifetime checks must all remain")
        require(lifetime.forall(x => x.io.waitingLoad.nonEmpty == enabled &&
            x.io.acceptedProducerWrite.nonEmpty == enabled))
        require(backend.registeredMemoryPreparationDescriptor && backend.backendNaturalAlignedPmp)
        require(backend.preparationDescriptor.map(_.getWidth).contains(275) &&
            backend.preparationDescriptorValid.map(_.getWidth).contains(1))
        ujson.Obj(
            "schema" -> "early-load-descriptor-actual-v1",
            "experimentalFlag" -> "earlyLoadPreparationDescriptor",
            "observedFlags" -> ujson.Obj.from(flags.toSeq.sortBy(_._1).map { case (k, v) => k -> ujson.Bool(v) }),
            "selectorEarlyLoads" -> selectors.head.earlyLoads,
            "waitingLoadMaskBits" -> ujson.Num(waitingMaskBits),
            "sourceLifetimeChecks" -> lifetime.size,
            "pendingLoadLifetimeChecks" -> lifetime.count(_.io.waitingLoad.nonEmpty),
            "descriptorPayloadBits" -> 275,
            "descriptorValidBits" -> 1,
            "oldActualEqualsSavedOn" -> true,
            "qualificationInherited" -> false,
            "physicalQualification" -> false
        )
    }
}

/** Fresh CHIRRTL only. Existing descriptor, PMP and next-line registration stay enabled. */
object EarlyLoadDescriptorBoardGsimMain extends App {
    require(args.length == 3 && Set("early-off", "early-on").contains(args(1)),
        "usage: fresh-output-directory early-off|early-on saved-production-on-actual-json")
    val out = Paths.get(args(0)).toAbsolutePath
    val enabled = args(1) == "early-on"
    require(!Files.exists(out), "fresh output directory required")
    val referencePath = Paths.get(args(2))
    val reference = ujson.read(Files.readString(referencePath))
    require(reference("schema") == ujson.Str("combined-timing-repair-r1-platform-actual-v1"))
    val config = CombinedTimingRepairR1Profile.config(true)
    var built: Option[BoardSocGsim] = None
    val fir = ChiselStage.emitCHIRRTL {
        val dut = FpgaNextBoardGsim.build(config, verifyConfiguration = true,
            sharedTwoWordFetchPmp = true, disjointEvictionStoreOverlap = true,
            proofBankControlDecoupling = true, projectedRequestHead = true,
            factorPreparedStorePool = true, combinedTimingR1Audit = true,
            registerNextLineDecision = true, registeredMemoryPreparationDescriptor = true,
            backendNaturalAlignedPmp = true, earlyLoadPreparationDescriptor = enabled)
        built = Some(dut)
        dut
    }
    val dut = built.get
    val actual = CombinedTimingRepairR1Audit.json(
        CombinedTimingRepairR1Audit.capturePlatform(dut.observedPlatform, config, true))
    require(actual == reference, "existing complete actual profile differs from saved production ON")
    val experimental = EarlyLoadDescriptorActualAudit.capture(dut, enabled)
    val hardware = fir.replaceAll(" @\\[[^\\n]*?\\]", "")
    Files.createDirectories(out)
    Files.writeString(out.resolve("BoardSocGsim.fir"), fir)
    Files.writeString(out.resolve("BoardSocGsim.hardware.fir"), hardware)
    Files.writeString(out.resolve("actual-combined-timing-repair-gsim.json"), actual.render(indent = 2) + "\n")
    Files.writeString(out.resolve("actual-early-load-descriptor.json"), experimental.render(indent = 2) + "\n")
    CombinedTimingRepairR1FabricAudit.write(out.toString)
    Files.writeString(out.resolve("emission.json"), ujson.Obj(
        "schema" -> "early-load-descriptor-chirrtl-v1",
        "top" -> "BoardSocGsim", "arm" -> args(1),
        "oldActualEqualsSavedOn" -> true,
        "referenceActualSha256" -> CombinedTimingRepairR1Emission.hash(Files.readAllBytes(referencePath)),
        "chirrtlSha256" -> CombinedTimingRepairR1Emission.hash(fir.getBytes(java.nio.charset.StandardCharsets.UTF_8)),
        "hardwareChirrtlSha256" -> CombinedTimingRepairR1Emission.hash(hardware.getBytes(java.nio.charset.StandardCharsets.UTF_8)),
        "qualificationInherited" -> false, "physicalQualification" -> false
    ).render(indent = 2) + "\n")
    println(s"PASS_EARLY_LOAD_DESCRIPTOR_BOARD early=$enabled oldActualExactlySavedOn=true core=179 profile=96 cpuHz=100000000")
}
