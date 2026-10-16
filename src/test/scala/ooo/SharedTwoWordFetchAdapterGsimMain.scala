package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}

/** New experimental caller qualification; no inherited frozen-profile qualification. */
object SharedTwoWordFetchAdapterGsimMain extends App {
    require(args.length == 2, "output directory and experimental board export experiment.json required")
    val out = Paths.get(args(0))
    val reference = ujson.read(Files.readString(Paths.get(args(1))))
    val c = ThreeProofRowNativeProfile.config
    val p = c.coreParams
    require(reference("schema").str == "experimental-shared-two-word-fetch-pmp-board-v1")
    require(reference("core") == ujson.read(PostedBoardConfiguration.json(p)))
    require(reference("profile") == ujson.read(PostedBoardConfiguration.json(c)))
    val order = ujson.Obj("core" -> ujson.Arr.from(p.productElementNames),
        "profile" -> ujson.Arr.from(c.productElementNames))
    require(reference("fieldOrder") == order, "actual caller product order differs from board export")
    require(p.productArity == 178 && c.productArity == 95 && p.renameWidth == 2)
    require(p.fetchReplyTurnover && p.fetchIdentityTranslation && p.alignedFetchSinglePage && p.fetchReadyDataClear)
    // Explicit effective tuple selected by the current native MachinePlatform caller:
    // p.copy(machineSystem = true, virtualMemoryLevels = translationLevels, pmpEntries = 16),
    // where native BoardSocTop supplies translationLevels = 3.
    val expectedAdapter = p.copy(machineSystem = true, virtualMemoryLevels = 3, pmpEntries = 16)
    var built: Option[InstructionPermissionGsim] = None
    ChiselStage.emitCHIRRTLFile({
        val dut = new InstructionPermissionGsim(2, retimed = true, aligned = true,
            turnover = true, identity = true, exactParams = Some(expectedAdapter), compareSharedTwoWord = true)
        built = Some(dut)
        dut
    }, Array("--target-dir", out.toString))
    val off = built.get.adapter
    val on = built.get.pairedAdapter.get
    require(off.p == expectedAdapter && on.p == expectedAdapter, "actual paired adapter parameters differ")
    require(!off.sharedTwoWordFetchPmp && on.sharedTwoWordFetchPmp)
    def actual(a: soc.core.ooo.InstructionTranslationAdapter): ujson.Value = ujson.Obj(
        "p" -> ujson.read(PostedBoardConfiguration.json(a.p)),
        "sharedTwoWordFetchPmp" -> a.sharedTwoWordFetchPmp,
        "packetWords" -> a.io.virtual.requestMask.getWidth)
    require(off.io.virtual.requestMask.getWidth == 2 && on.io.virtual.requestMask.getWidth == 2)
    Files.writeString(out.resolve("experimental-adapter-config.json"), ujson.Obj(
        "schema" -> "experimental-shared-two-word-adapter-pair-v1",
        "core" -> ujson.read(PostedBoardConfiguration.json(p)),
        "profile" -> ujson.read(PostedBoardConfiguration.json(c)),
        "fieldOrder" -> order,
        "coreFields" -> 178, "profileFields" -> 95,
        "adapterSelection" -> "current native caller p.copy(machineSystem=true, virtualMemoryLevels=3, pmpEntries=16)",
        "expectedAdapterParams" -> ujson.read(PostedBoardConfiguration.json(expectedAdapter)),
        "actualOffAdapter" -> actual(off), "actualOnAdapter" -> actual(on),
        "boardBindingScope" -> "core/profile values and field order matched to export; effective caller tuple checked against current constructor definition",
        "comparison" -> "complete same-input real OFF/ON adapter IO every cycle",
        "oracleScope" -> "architecturally offered and owned transactions only",
        "frontendQualified" -> false, "wholeBoardQualified" -> false,
        "physicalQualification" -> false).render(indent = 2) + "\n")
}
