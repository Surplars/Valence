package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** In-memory construction only: no FIRRTL/native output, simulator model, or execution. */
object YoungLoadSealMergedGate extends App {
    require(args.length == 1, "fresh report directory required")
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out))
    Files.createDirectories(out)
    val young = YoungLoadSealSourceBridge.candidate(NearTermAProfile.onOptions :+ YoungLoadSealSourceBridge.flag)
    val raw = MacRawHandoffEntry.on
    val cases = Seq("young-on-mac-off" -> young, "young-off-mac-on" -> raw)
    for ((label, c) <- cases) {
        PlacedTimingProfileBridge.requireShape(c)
        YoungLoadSealSourceBridge.requireCompatible(c)
        var observed: Option[Map[String, Any]] = None
        ChiselStage.elaborate {
            val dut = new FpgaNextSocTop(c, bscanChain = 2)
            val core = dut.board.platform.core.core.core
            require(core.p == c.coreParams && core.backend.p == c.coreParams,
                "actual full core/backend constructor differs from the complete profile")
            require(core.backend.p.postedYoungerLoadSealDeferral == c.postedYoungerLoadSealDeferral,
                "actual IntegerBackend lost younger-load seal deferral")
            val mac = MacRawHandoffEntryAudit.capture(dut.board, c)
            val a = NearTermAActualAudit.capture(dut.board.platform, c)
            observed = Some(Map("schema" -> "young-load-seal-merged-actual-constructor-v1",
                "case" -> label, "scope" -> "in-memory-actual-construction-only",
                "postedYoungerLoadSealDeferral" -> core.backend.p.postedYoungerLoadSealDeferral,
                "completeCoreAndBackendEqual" -> true, "mac" -> mac, "nearTermA" -> a,
                "newCpuModel" -> false, "simulationRun" -> false, "physicalQualification" -> false))
            dut
        }
        require(observed.isDefined)
        PostedBoardConfiguration.write(c, out.resolve(label).toString)
        YoungLoadSealSourceBridge.write(c, out.resolve(label).toString)
        Files.writeString(out.resolve(label + ".json"), PostedBoardConfiguration.json(observed.get) + "\n")
    }
    for ((label, c) <- Seq("off" -> NearTermAProfile.on, "on" -> young)) {
        PostedBoardConfiguration.write(c, out.resolve("profile-" + label).toString)
        YoungLoadSealSourceBridge.write(c, out.resolve("profile-" + label).toString)
    }
    val old = PostedBoardConfiguration.document(NearTermAProfile.on) ++ Map(
        "profile" -> PlacedTimingProfileBridge.historicalAFields(NearTermAProfile.on),
        "core" -> PlacedTimingProfileBridge.historicalAFields(NearTermAProfile.on.coreParams))
    Files.writeString(out.resolve("published-a-projection.json"), PostedBoardConfiguration.json(old) + "\n")
    println(s"PASS_MERGED_ACTUAL_CONSTRUCTORS core=${young.coreParams.productArity} profile=${young.productArity} " +
        "projected-core=173 projected-profile=90 held=false no-model-no-simulation")
}
