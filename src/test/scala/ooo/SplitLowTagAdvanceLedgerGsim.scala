package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo._
import soc.platform.CommonA1RebuildProfile
import java.nio.charset.StandardCharsets
import java.nio.file.{Files, Paths}

/** Exact guarded-natural profile pair; scalar wrapper only for GSIM, untapped ROB for mapping. */
object SplitLowTagAdvanceLedgerGsimMain extends App {
    require(args.length >= 2 && Set("control", "split").contains(args(1)),
        "output directory and control|split are required")
    require(args.length <= 3 && args.lift(2).forall(_ == "untapped"))
    val target = args(0)
    val control = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProofGuardedNaturalPmp.config.coreParams
    val p = control.copy(splitLowTagAdvance = args(1) == "split")
    require(p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64)
    require(p.renameWidth == 2 && p.commitWidth == 2 && p.completionWidth == 2 && p.recoveryWidth == 4)
    require(!p.moveAlias && p.fastHeadTrapRecovery && p.fastHeadSystemRecovery)
    Files.createDirectories(Paths.get(target))
    def quote(s: String): String = "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
    val params = p.productElementNames.zip(p.productIterator).map { case (name, value) =>
        "  " + quote(name) + ": " + quote(value.toString)
    }.mkString("{\n", ",\n", "\n}\n")
    Files.write(Paths.get(target, "effective-params.json"), params.getBytes(StandardCharsets.UTF_8))
    if (args.lift(2).contains("untapped"))
        ChiselStage.emitCHIRRTLFile(new RenameRob(p), Array("--target-dir", target))
    else ChiselStage.emitCHIRRTLFile(new RenameRobGsim(p), Array("--target-dir", target))
}
