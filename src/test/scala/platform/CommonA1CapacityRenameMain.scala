package platform

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import ooo.RenameRobGsim
import soc.platform._

/** Ledger-only component fixture, with the exact Common CPU resolved parameters.
  * Completion inputs are synthetic; this is not execution-unit or full-CPU coverage.
  */
object CommonA1CapacityRenameMain extends App {
    require(args.length == 3, "fresh output directory, ROB and PRF required")
    val output = Paths.get(args(0))
    require(!Files.exists(output), "fresh output directory required")
    val profile = CommonCpuProfile.A1
    val spec = CommonA1CpuSpec(4, args(1).toInt, args(2).toInt)
    val config = CommonA1CpuSpec.resolve(profile, None, Some(spec), profile.boundary)
    val p = config.coreParams
    ChiselStage.emitCHIRRTLFile(new RenameRobGsim(p), Array("--target-dir", output.toString))
    CommonCpuMicroarchitectureIdentity.write(output.resolve("microarchitecture-identity.json"),
        CommonCpuMicroarchitectureIdentity.build(profile, None, profile.boundary, cpuSpec = Some(spec)))
    Files.writeString(output.resolve("driver-defines.json"), ujson.write(ujson.Obj(
        "ROB_ENTRIES" -> p.robEntries, "PHYSICAL_REGS" -> p.physicalRegs,
        "TAG_BITS" -> p.tagBits, "RECOVERY_WIDTH" -> p.recoveryWidth,
        "FAST_HEAD_TRAP" -> (if (p.fastHeadTrapRecovery) 1 else 0),
        "FAST_HEAD_SYSTEM" -> (if (p.fastHeadSystemRecovery) 1 else 0),
        "COMMON_CAPACITY" -> 1), indent = 2) + "\n")
}
