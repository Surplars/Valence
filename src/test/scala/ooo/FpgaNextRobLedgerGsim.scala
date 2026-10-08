package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo._
import java.nio.charset.StandardCharsets
import java.nio.file.{Files, Paths}

/** Focused exact-profile qualification; only the comparison storage topology varies. */
object FpgaNextRobLedgerGsimMain extends App {
    require(args.length == 2, "output directory and registers|banked are required")
    require(Set("registers", "banked").contains(args(1)))
    val target = args(0)
    val p = FpgaNextConfig.Candidate.coreParams.copy(bankedRobPayload = args(1) == "banked")
    require(p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64)
    require(p.renameWidth == 2 && p.commitWidth == 2 && p.completionWidth == 2 && p.recoveryWidth == 4)
    require(!p.moveAlias && p.fastHeadTrapRecovery && p.fastHeadSystemRecovery)
    Files.createDirectories(Paths.get(target))
    def quote(s: String): String = "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
    val params = p.productElementNames.zip(p.productIterator).map { case (name, value) =>
        "  " + quote(name) + ": " + quote(value.toString)
    }.mkString("{\n", ",\n", "\n}\n")
    Files.write(Paths.get(target, "effective-params.json"), params.getBytes(StandardCharsets.UTF_8))
    ChiselStage.emitCHIRRTLFile(new RenameRobGsim(p), Array("--target-dir", target))
}
