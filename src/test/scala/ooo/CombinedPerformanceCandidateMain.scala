package ooo

import _root_.circt.stage.ChiselStage
import chisel3.experimental.BaseModule
import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Explicit diagnostic profile only; production constructor defaults remain unchanged. */
object CombinedPerformanceCandidateProfile {
    val config = CombinedTimingRepairR1Profile.config(true)
    def construct(on: Boolean): FpgaNextSocTop = new FpgaNextSocTop(
        config = config, debug = CombinedTimingPmpR1Profile.debug,
        bscanChain = CombinedTimingPmpR1Profile.bscanChain,
        preselectRedirectTokenMatches = false, sharedTwoWordFetchPmp = true,
        disjointEvictionStoreOverlap = true, projectedRequestHead = true, factorPreparedStorePool = true,
        proofBankControlDecoupling = true, registerNextLineDecision = true,
        registeredMemoryPreparationDescriptor = true, backendNaturalAlignedPmp = true,
        earlyLoadPreparationDescriptor = on, dataTlbMissCacheEntries = (if (on) 64 else 0),
        virtualStoreOperandLookahead = on, bankedStoreData = on)
    def descendants(m: BaseModule): Seq[BaseModule] = {
        val children = classOf[BaseModule].getMethod("getIds").invoke(m)
            .asInstanceOf[scala.collection.Iterable[_]].collect { case x: BaseModule => x }.toSeq
        m +: children.flatMap(descendants)
    }
    def actual(p: MachinePlatform, on: Boolean): ujson.Value = {
        val b = p.core.core.core.backend
        val levels = Seq(p, p.core, p.core.core, p.core.core.core, b)
        val switches = Seq("earlyLoadPreparationDescriptor", "virtualStoreOperandLookahead", "bankedStoreData")
        val observed = levels.map { m =>
            val flags = switches.map { key =>
                val value = m.getClass.getMethod(key).invoke(m).asInstanceOf[Boolean]
                require(value == on, s"actual ${m.getClass.getSimpleName}.$key mismatch")
                key -> ujson.Bool(value)
            }
            m.getClass.getSimpleName -> ujson.Obj.from(flags)
        }
        val modules = descendants(p).distinct
        val services = modules.collect { case x: SvTranslationService => x }
        require(services.size == 2)
        val i = services.find(_.entries == 8).get
        val d = services.find(_.entries == 16).get
        require(i.missCacheEntries == 0 && !i.loadPeek && !i.writeReadReuse)
        require(d.missCacheEntries == (if (on) 64 else 0) && d.loadPeek && d.writeReadReuse)
        require(i.maxLevels == 3 && d.maxLevels == 3)
        require(p.dataTlbMissCacheEntries == d.missCacheEntries)
        val selectors = modules.collect { case x: MemoryPreparationDescriptorSelector => x }
        require(selectors.size == 1 && selectors.head.earlyLoads == on)
        if (on) require(selectors.head.io.waitingLoads.get.getWidth == 16)
        require(b.preparationDescriptor.get.getWidth == 275 && b.preparationDescriptorValid.get.getWidth == 1)
        require(b.physicalReads.length == 12 && b.issuePayloadReads.length == 8)
        require(b.storeDataRam.isDefined == on)
        if (on) require(b.storeDataRam.get.io.address.length == 2)
        require(!config.translatedResponseEmptyFlow && !config.frozenStoreCheckedFlow)
        ujson.Obj("schema" -> "combined-performance-actual-v1", "observedSwitches" -> ujson.Obj.from(observed),
            "I1" -> i.entries, "I2" -> i.missCacheEntries, "D1" -> d.entries, "D2" -> d.missCacheEntries,
            "selectorEarlyLoads" -> selectors.head.earlyLoads, "descriptorPayloadBits" -> 275,
            "descriptorValidBits" -> 1, "physicalReadPorts" -> b.physicalReads.length,
            "issuePayloadGroups" -> b.issuePayloadReads.length, "storeDataDeclaredFunctionalReadPorts" -> (if (on) 2 else 0),
            "oldProfileEqualsSaved50cb" -> true, "physicalQualification" -> false)
    }
}

object CombinedPerformanceCandidateNativeMain extends App {
    require(args.length == 3 && Set("off", "on").contains(args(1)))
    val out = Paths.get(args(0)); require(!Files.exists(out))
    val on = args(1) == "on"
    var built: Option[FpgaNextSocTop] = None
    val fir = ChiselStage.emitCHIRRTL {
        val dut = CombinedPerformanceCandidateProfile.construct(on); built = Some(dut); dut
    }
    val dut = built.get
    val actual = CombinedTimingRepairR1Audit.capture(dut, CombinedPerformanceCandidateProfile.config, true)
    require(CombinedTimingRepairR1Audit.json(actual) == ujson.read(Files.readString(Paths.get(args(2)))))
    require(dut.earlyLoadPreparationDescriptor == on && dut.board.earlyLoadPreparationDescriptor == on)
    require(dut.virtualStoreOperandLookahead == on && dut.board.virtualStoreOperandLookahead == on)
    require(dut.bankedStoreData == on && dut.board.bankedStoreData == on)
    require(dut.dataTlbMissCacheEntries == (if (on) 64 else 0) &&
        dut.board.dataTlbMissCacheEntries == dut.dataTlbMissCacheEntries)
    val flags = CombinedPerformanceCandidateProfile.actual(dut.board.platform, on)
    CombinedTimingRepairR1Emission.write(out, "FpgaNextSocTop", fir, actual, true)
    Files.writeString(out.resolve("actual-combined-performance.json"), flags.render(indent = 2) + "\n")
}

object CombinedPerformanceCandidateBoardMain extends App {
    require(args.length == 3 && Set("off", "on").contains(args(1)))
    val out = Paths.get(args(0)); require(!Files.exists(out))
    val on = args(1) == "on"
    val c = CombinedPerformanceCandidateProfile.config
    var built: Option[BoardSocGsim] = None
    val fir = ChiselStage.emitCHIRRTL {
        val dut = FpgaNextBoardGsim.build(c, verifyConfiguration = true, sharedTwoWordFetchPmp = true,
            disjointEvictionStoreOverlap = true, proofBankControlDecoupling = true,
            projectedRequestHead = true, factorPreparedStorePool = true, combinedTimingR1Audit = true,
            registerNextLineDecision = true, registeredMemoryPreparationDescriptor = true,
            backendNaturalAlignedPmp = true, earlyLoadPreparationDescriptor = on,
            dataTlbMissCacheEntries = (if (on) 64 else 0), virtualStoreOperandLookahead = on, bankedStoreData = on)
        built = Some(dut); dut
    }
    val dut = built.get
    val actual = CombinedTimingRepairR1Audit.capturePlatform(dut.observedPlatform, c, true)
    require(CombinedTimingRepairR1Audit.json(actual) == ujson.read(Files.readString(Paths.get(args(2)))))
    require(dut.earlyLoadPreparationDescriptor == on && dut.virtualStoreOperandLookahead == on && dut.bankedStoreData == on)
    require(dut.dataTlbMissCacheEntries == (if (on) 64 else 0))
    val flags = CombinedPerformanceCandidateProfile.actual(dut.observedPlatform, on)
    CombinedTimingRepairR1Emission.write(out, "BoardSocGsim", fir, actual, true)
    CombinedTimingRepairR1FabricAudit.write(out.toString)
    Files.writeString(out.resolve("actual-combined-performance.json"), flags.render(indent = 2) + "\n")
    Files.writeString(out.resolve("actual-combined-timing-repair-gsim.json"),
        CombinedTimingRepairR1Audit.json(actual).render(indent = 2) + "\n")
}
