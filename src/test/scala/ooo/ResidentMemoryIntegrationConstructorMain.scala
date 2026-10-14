package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Real native Board constructors only; no GSIM export, firtool, model or simulation. */
object ResidentMemoryIntegrationConstructorMain extends App {
    require(args.length == 1, "fresh constructor report directory required")
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "constructor report directory must be fresh")
    Files.createDirectories(out)
    val profile = ResidentMemoryIntegrationProfile
    for ((label, c, options) <- Seq(("off", profile.off, profile.offOptions),
            ("on", profile.on, profile.onOptions))) {
        profile.requireSide(label, options, c)
        var observed: Option[Map[String, Any]] = None
        ChiselStage.elaborate {
            val dut = new FpgaNextSocTop(c, bscanChain = 2)
            val resident = ResidentMemoryIntegrationActualAudit.capture(dut.board.platform, c)
            val held = HeldAluIntegrationActualAudit.capture(dut.board.platform, c)
            val mac = MacRawHandoffEntryAudit.capture(dut.board, c)
            require(dut.board.platform.core.core.core.p.lvtPhysicalRegisterFile,
                "actual complete board lost requested LVT storage")
            observed = Some(Map("resident" -> resident, "held" -> held, "mac" -> mac,
                "lvtPhysicalRegisterFile" -> true, "gsimEmission" -> false,
                "modelBuild" -> false, "simulationRun" -> false, "physicalQualification" -> false))
            dut
        }
        require(observed.isDefined, "actual Board constructor audit did not complete")
        val side = out.resolve(label)
        PostedBoardConfiguration.write(c, side.toString)
        profile.write(c, side.toString)
        Files.writeString(side.resolve("actual-constructor.json"),
            PostedBoardConfiguration.json(observed.get) + "\n")
        println(s"PASS_RESIDENT_ACTUAL_CONSTRUCTOR side=$label core=175 profile=92 held=false raw=false")
    }
}
