package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}

/** One source-pinned native export. No simulation, physical tools, old CLI, or config override. */
object C1PhysicalNativeMain extends App {
    require(args.length == 4 && Set("0", "1").contains(args(2)) && Set("0", "1").contains(args(3)), "fresh native output and immutable qualified CPU actual directory required")
    val c1Enabled = args(2) == "1"
    val c0Enabled = args(3) == "1"
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
    var constructorActual: Option[Map[String, Any]] = None
    var actual: Option[Map[String, Any]] = None
    var constructed: Option[soc.core.ooo.FpgaNextSocTop] = None
    ChiselStage.emitSystemVerilogFile({
        val dut = new soc.core.ooo.FpgaNextSocTop(config = c, debug = ThreeProofRowNativeProfile.debug,
            bscanChain = ThreeProofRowNativeProfile.bscanChain, preselectRedirectTokenMatches = c0Enabled,
            proofBankControlDecoupling = c1Enabled)
        val backend = dut.board.platform.core.core.core.backend
        require(dut.proofBankControlDecoupling == c1Enabled)
        require(backend.shadowEarlyProofBind == c1Enabled && backend.proofBankQuiesceIntent == c1Enabled &&
            backend.proofBankOwnerCleanup == c1Enabled)
        require(backend.pendingStoreProof.get.ownerStateCleanup == c1Enabled &&
            backend.pendingStoreProof.get.checkBindPlanning == c1Enabled &&
            backend.lsu.observeOrdinaryLoadCapacity == c1Enabled)
        constructorActual = Some(Map("topClass" -> dut.getClass.getName,
            "backendClass" -> backend.getClass.getName,
            "backendPath" -> "board.platform.core.core.core.backend",
            "c0PreselectedRedirect" -> backend.preselectRedirectTokenMatches,
            "shadowEarlyProofBind" -> backend.shadowEarlyProofBind,
            "proofBankQuiesceIntent" -> backend.proofBankQuiesceIntent,
            "proofBankOwnerCleanup" -> backend.proofBankOwnerCleanup,
            "bankOwnerStateCleanup" -> backend.pendingStoreProof.get.ownerStateCleanup,
            "bankCheckBindPlanning" -> backend.pendingStoreProof.get.checkBindPlanning,
            "lsuOrdinaryLoadCapacity" -> backend.lsu.observeOrdinaryLoadCapacity,
            "fastHeadTrapRecovery" -> backend.p.fastHeadTrapRecovery,
            "fastHeadSystemRecovery" -> backend.p.fastHeadSystemRecovery,
            "fastBufferedStoreRetire" -> backend.p.fastBufferedStoreRetire))
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
    require(constructorActual.nonEmpty)
    val bankSv = Files.readString(out.resolve("PendingVirtualStoreProof.sv"))
    require(bankSv.contains("io_currentPendingLoadMask") == c1Enabled,
        "emitted proof-bank interface must correspond to the actual C1 constructor mode")
    Files.writeString(out.resolve("actual-c1-constructors.json"),
        PostedBoardConfiguration.json(constructorActual.get) + "\n")
    Files.writeString(out.resolve("actual-native.json"), PostedBoardConfiguration.json(completed) + "\n")
    Files.writeString(out.resolve("actual-core-parameters.json"), PostedBoardConfiguration.json(c.coreParams) + "\n")
    Files.writeString(out.resolve("native-entry.json"), ujson.Obj(
        "schema" -> "three-proof-row-explicit-c1-native-entry-v1", "identity" -> ThreeProofRowNativeProfile.identity,
        "configurationSource" -> "explicit95 named constructor; no old option list or hidden override",
        "c1ProofControlDecoupling" -> c1Enabled,
        "shadowEarlyProofBind" -> ujson.Bool(constructorActual.get("shadowEarlyProofBind").asInstanceOf[Boolean]),
        "proofBankQuiesceIntent" -> ujson.Bool(constructorActual.get("proofBankQuiesceIntent").asInstanceOf[Boolean]),
        "proofBankOwnerCleanup" -> ujson.Bool(constructorActual.get("proofBankOwnerCleanup").asInstanceOf[Boolean]),
        "c0PreselectedRedirect" -> c0Enabled, "coreFields" -> 178, "profileFields" -> 95, "proofRows" -> 3, "earlyCredits" -> 2,
        "standaloneTapEnabled" -> false, "bscanEnabled" -> true, "bscanChain" -> 2,
        "ramLoaderEnabled" -> true, "nativeMacEnabled" -> true, "rawHandoffEnabled" -> true,
        "requiredPhysicalMacGenerics" -> ujson.Obj("NATIVE_MAC_LOCAL_PAD_RESET_RELEASE" -> 1,
            "NATIVE_MAC_REGISTER_SELECTED_HALF" -> 1),
        "nativeMacPhysicalGenericsApplied" -> false, "physicalQualification" -> false).render(indent = 2) + "\n")
    println("PASS_C1_NATIVE_ACTUAL core=178 profile=95 rows=3 credits=2 native_mac=true bscan=2 ram_loader=true no_physical")
}
