package platform

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.platform._

/** Normal CPU-tile synthesis input for the three separately measured capacities.
  * No GSIM wrapper, test bores, runtime profile or production-default change.
  */
object CommonA1CapacityTileMain extends App {
    require(args.length == 3, "fresh output-directory rob-entries physical-registers")
    val spec = CommonA1CpuSpec(4, args(1).toInt, args(2).toInt)
    require(Set((16, 48), (16, 64), (32, 64)).contains((spec.robEntries, spec.physicalRegs)),
        "matched synthesis inputs select ROB/PRF 16/48, 16/64 or 32/64 with LSU4")
    val out = Paths.get(args(0))
    require(!Files.exists(out), "fresh output directory required")
    val profile = CommonCpuProfile.A1
    val boundary = profile.boundary
    val config = CommonA1CpuSpec.resolve(profile, None, Some(spec), boundary)
    Files.createDirectories(out)
    CommonCpuMicroarchitectureIdentity.write(out.resolve("cpu-identity.json"),
        CommonCpuMicroarchitectureIdentity.build(profile, None, boundary, cpuSpec = Some(spec)))
    CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-config.json"), config)
    CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-parameters.json"), config.coreParams)
    ChiselStage.emitSystemVerilogFile(new CommonA1CpuTile(config, boundary, None),
        Array("--target-dir", out.toString),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables", "--default-layer-specialization=enable",
            "--verification-flavor=if-else-fatal"))
}
