package ooo

import _root_.circt.stage.ChiselStage
import chisel3.experimental.BaseModule
import java.nio.file.{Files, Paths}
import soc.core.ooo.{FpgaNextSocTop, MemoryPreparationDescriptorSelector}

/** Separate native physical-top emission; never substitutes a GSIM envelope. */
object EarlyLoadDescriptorNativeMain extends App {
    require(args.length == 2, "fresh-output-directory saved-repair-on-native-actual-json")
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh output directory required")
    val reference = ujson.read(Files.readString(Paths.get(args(1))))
    val config = CombinedTimingRepairR1Profile.config(true)
    var built: Option[FpgaNextSocTop] = None
    val fir = ChiselStage.emitCHIRRTL {
        val dut = new FpgaNextSocTop(config = config, debug = CombinedTimingPmpR1Profile.debug,
            bscanChain = CombinedTimingPmpR1Profile.bscanChain, preselectRedirectTokenMatches = false,
            sharedTwoWordFetchPmp = true, disjointEvictionStoreOverlap = true,
            projectedRequestHead = true, factorPreparedStorePool = true,
            proofBankControlDecoupling = true, registerNextLineDecision = true,
            registeredMemoryPreparationDescriptor = true, backendNaturalAlignedPmp = true,
            earlyLoadPreparationDescriptor = true)
        built = Some(dut); dut
    }
    val dut = built.get
    val actual = CombinedTimingRepairR1Audit.capture(dut, config, true)
    require(CombinedTimingRepairR1Audit.json(actual) == reference,
        "every existing native actual field must equal frozen repair-ON")
    val platform = dut.board.platform
    val backend = platform.core.core.core.backend
    val flags = Map("fpgaNextSocTop" -> dut.earlyLoadPreparationDescriptor,
        "boardSocTop" -> dut.board.earlyLoadPreparationDescriptor,
        "machinePlatform" -> platform.earlyLoadPreparationDescriptor,
        "mappedMachineCore" -> platform.core.earlyLoadPreparationDescriptor,
        "machineCore" -> platform.core.core.earlyLoadPreparationDescriptor,
        "integerCore" -> platform.core.core.core.earlyLoadPreparationDescriptor,
        "integerBackend" -> backend.earlyLoadPreparationDescriptor)
    require(flags.values.forall(identity))
    def descendants(m: BaseModule): Seq[BaseModule] = {
        val children = classOf[BaseModule].getMethod("getIds").invoke(m)
            .asInstanceOf[scala.collection.Iterable[_]].collect { case child: BaseModule => child }.toSeq
        m +: children.flatMap(descendants)
    }
    val selectors = descendants(backend).distinct.collect { case x: MemoryPreparationDescriptorSelector => x }
    require(selectors.size == 1 && selectors.head.earlyLoads && selectors.head.io.waitingLoads.get.getWidth == 16)
    require(backend.preparationDescriptor.get.getWidth == 275 && backend.preparationDescriptorValid.get.getWidth == 1)
    CombinedTimingRepairR1Emission.write(out, "FpgaNextSocTop", fir, actual, true)
    Files.writeString(out.resolve("actual-early-load-native.json"), ujson.Obj(
        "schema" -> "early-load-descriptor-native-actual-v1",
        "observedFlags" -> ujson.Obj.from(flags.toSeq.sortBy(_._1).map { case (k, v) => k -> ujson.Bool(v) }),
        "selectorEarlyLoads" -> true, "waitingLoadMaskBits" -> 16,
        "descriptorPayloadBits" -> 275, "descriptorValidBits" -> 1,
        "physicalReadPorts" -> backend.physicalReads.length,
        "issuePayloadGroups" -> backend.issuePayloadReads.length,
        "oldNativeActualEqualsSavedOn" -> true, "physicalQualification" -> false
    ).render(indent = 2) + "\n")
    println("PASS_EARLY_LOAD_NATIVE_ACTUAL core=179 profile=96 ports=76 UNQUALIFIED")
}
