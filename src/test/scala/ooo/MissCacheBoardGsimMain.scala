package ooo
import _root_.circt.stage.ChiselStage
import chisel3.experimental.BaseModule
import java.nio.file.{Files, Paths}
import soc.core.ooo.SvTranslationService
object MissCacheActualAudit {
  private def descendants(m: BaseModule): Seq[BaseModule] = {
    val children = classOf[BaseModule].getMethod("getIds").invoke(m)
      .asInstanceOf[scala.collection.Iterable[_]].collect { case x: BaseModule => x }.toSeq
    m +: children.flatMap(descendants)
  }
  def capture(dut: BoardSocGsim, enabled: Boolean): ujson.Value = {
    val services = descendants(dut.observedPlatform).collect { case x: SvTranslationService => x }.distinct
    require(services.size == 2)
    val i = services.find(_.entries == 8).get
    val d = services.find(_.entries == 16).get
    require(i.missCacheEntries == 0 && !i.loadPeek && !i.writeReadReuse)
    require(d.missCacheEntries == (if (enabled) 64 else 0) && d.loadPeek && d.writeReadReuse)
    require(i.maxLevels == 3 && d.maxLevels == 3)
    require(dut.dataTlbMissCacheEntries == d.missCacheEntries &&
      dut.observedPlatform.dataTlbMissCacheEntries == d.missCacheEntries)
    ujson.Obj("schema" -> "miss-cache-actual-v1", "I1" -> i.entries, "I2" -> i.missCacheEntries,
      "D1" -> d.entries, "D2" -> d.missCacheEntries, "Dpeek" -> d.loadPeek,
      "DwriteReadReuse" -> d.writeReadReuse, "maxLevels" -> d.maxLevels,
      "oldActualEqualsSavedOn" -> true, "physicalQualification" -> false)
  }
}
/** Fresh CHIRRTL only. Existing descriptor, PMP and next-line registration stay enabled. */
object MissCacheBoardGsimMain extends App {
    require(args.length == 3 && Set("l2-off", "l2-on").contains(args(1)),
        "usage: fresh-output-directory l2-off|l2-on saved-production-on-actual-json")
    val out = Paths.get(args(0)).toAbsolutePath
    val enabled = args(1) == "l2-on"
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
            backendNaturalAlignedPmp = true, dataTlbMissCacheEntries = (if (enabled) 64 else 0))
        built = Some(dut)
        dut
    }
    val dut = built.get
    val actual = CombinedTimingRepairR1Audit.json(
        CombinedTimingRepairR1Audit.capturePlatform(dut.observedPlatform, config, true))
    require(actual == reference, "existing complete actual profile differs from saved production ON")
    val experimental = MissCacheActualAudit.capture(dut, enabled)
    val hardware = fir.replaceAll(" @\\[[^\\n]*?\\]", "")
    Files.createDirectories(out)
    Files.writeString(out.resolve("BoardSocGsim.fir"), fir)
    Files.writeString(out.resolve("BoardSocGsim.hardware.fir"), hardware)
    Files.writeString(out.resolve("actual-combined-timing-repair-gsim.json"), actual.render(indent = 2) + "\n")
    Files.writeString(out.resolve("actual-miss-cache.json"), experimental.render(indent = 2) + "\n")
    CombinedTimingRepairR1FabricAudit.write(out.toString)
    Files.writeString(out.resolve("emission.json"), ujson.Obj(
        "schema" -> "miss-cache-chirrtl-v1",
        "top" -> "BoardSocGsim", "arm" -> args(1),
        "oldActualEqualsSavedOn" -> true,
        "referenceActualSha256" -> CombinedTimingRepairR1Emission.hash(Files.readAllBytes(referencePath)),
        "chirrtlSha256" -> CombinedTimingRepairR1Emission.hash(fir.getBytes(java.nio.charset.StandardCharsets.UTF_8)),
        "hardwareChirrtlSha256" -> CombinedTimingRepairR1Emission.hash(hardware.getBytes(java.nio.charset.StandardCharsets.UTF_8)),
        "qualificationInherited" -> false, "physicalQualification" -> false
    ).render(indent = 2) + "\n")
    println(s"PASS_MISS_CACHE_BOARD enabled=$enabled oldActualExactlySavedOn=true core=179 profile=96 cpuHz=100000000")
}
