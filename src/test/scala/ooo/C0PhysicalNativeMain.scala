package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}

/** One source-pinned native export. No simulation, physical tools, old CLI, or config override. */
object C0PhysicalNativeMain extends App {
    require(args.length == 3 && Set("0", "1").contains(args(2)), "fresh native output and immutable qualified CPU actual directory required")
    val c0Enabled = args(2) == "1"
    val out = Paths.get(args(0)).toAbsolutePath
    val ref = Paths.get(args(1)).toAbsolutePath
    require(!Files.exists(out), "fresh native output required")
    def read(name: String): ujson.Value = ujson.read(Files.readString(ref.resolve(name)))
    val c = ThreeProofRowNativeProfile.config
    def json(x: Any): ujson.Value = ThreeProofRowNativeActualAudit.json(x)
    val order = Map("core" -> c.coreParams.productElementNames.toSeq, "profile" -> c.productElementNames.toSeq)
    require(json(order) == read("actual-product-field-order.json"), "complete 178/95 field order differs")
    require(json(c.coreParams) == read("actual-core-parameters.json"), "complete 178-field core differs")
    require(json(PostedBoardConfiguration.document(c)) == read("profile.json"), "complete profile/cache/DDR/network/derived document differs")
    PlacedTimingProfileBridge.requireShape(c)
    require(c.cpuHz == 100000000 && c.aonHz == 50000000 && c.uartHz == 50000000 && c.ddrUiHz == 250000000)
    require(!ThreeProofRowNativeProfile.debug.enabled && !ThreeProofRowNativeProfile.debug.externalDmi &&
        ThreeProofRowNativeProfile.bscanChain == 2)
    val expectedFabric = read("actual-fabric.json")
    val expectedThree = read("actual-three-proof-row-cpu.json")
    Files.createDirectories(out)
    PostedBoardConfiguration.write(c, out.toString)
    Files.writeString(out.resolve("actual-product-field-order.json"), PostedBoardConfiguration.json(order) + "\n")
    var actual: Option[Map[String, Any]] = None
    var constructed: Option[soc.core.ooo.FpgaNextSocTop] = None
    ChiselStage.emitSystemVerilogFile({
        val dut = new soc.core.ooo.FpgaNextSocTop(config = c, debug = ThreeProofRowNativeProfile.debug,
            bscanChain = ThreeProofRowNativeProfile.bscanChain, preselectRedirectTokenMatches = c0Enabled)
        val backend = dut.board.platform.core.core.core.backend
        require(backend.preselectRedirectTokenMatches == c0Enabled)
        require(backend.preselectedRedirectTokens.nonEmpty == c0Enabled)
        require(backend.redirectTokens.nonEmpty != c0Enabled)
        constructed = Some(dut)
        actual = Some(ThreeProofRowNativeActualAudit.capture(dut, c, expectedFabric, expectedThree))
        dut
    }, Array("--target-dir", out.toString),
       Array("--strip-debug-info", "--disable-all-randomization", "--default-layer-specialization=disable"))
    require(actual.nonEmpty && constructed.nonEmpty && Files.isRegularFile(out.resolve("FpgaNextSocTop.sv")))
    val completed = ThreeProofRowNativeActualAudit.captureClosedTop(constructed.get, actual.get)
    Files.writeString(out.resolve("actual-native.json"), PostedBoardConfiguration.json(completed) + "\n")
    Files.writeString(out.resolve("actual-core-parameters.json"), PostedBoardConfiguration.json(c.coreParams) + "\n")
    Files.writeString(out.resolve("native-entry.json"), ujson.Obj(
        "schema" -> "three-proof-row-explicit-native-entry-v1", "identity" -> ThreeProofRowNativeProfile.identity,
        "configurationSource" -> "explicit95 named constructor; no old option list or hidden override",
        "c0PreselectedRedirect" -> c0Enabled, "coreFields" -> 178, "profileFields" -> 95, "proofRows" -> 3, "earlyCredits" -> 2,
        "standaloneTapEnabled" -> false, "bscanEnabled" -> true, "bscanChain" -> 2,
        "ramLoaderEnabled" -> true, "nativeMacEnabled" -> true, "rawHandoffEnabled" -> true,
        "nativeMacPhysicalGenericsApplied" -> false, "physicalQualification" -> false).render(indent = 2) + "\n")
    println("PASS_C0_NATIVE_ACTUAL core=178 profile=95 rows=3 credits=2 native_mac=true bscan=2 ram_loader=true no_physical")
}
