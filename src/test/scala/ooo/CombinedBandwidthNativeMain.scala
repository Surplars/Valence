package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path, Paths}
import java.security.MessageDigest
import scala.jdk.CollectionConverters._
import soc.core.ooo.FpgaNextSocTop

/** Fresh, independently named experimental native export, without inherited qualification.
  * Native mode emits complete SystemVerilog and black-box resources. CHIRRTL modes
  * support a source-location-only default/OFF equivalence check and actual ON audit.
  */
object CombinedBandwidthNativeMain extends App {
    require(args.length == 2 && Set("native", "default", "off", "on").contains(args(1)),
        "fresh output directory and native/default/off/on mode required")
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh output directory required")
    val mode = args(1)
    val enabled = mode == "native" || mode == "on"
    val c = ThreeProofRowNativeProfile.config
    require(c.productArity == 95 && c.coreParams.productArity == 178)
    var built: Option[FpgaNextSocTop] = None
    def construct(): FpgaNextSocTop = {
        val dut = if (mode == "default") ThreeProofRowNativeProfile.construct() else
            new FpgaNextSocTop(config = c, debug = ThreeProofRowNativeProfile.debug,
                bscanChain = ThreeProofRowNativeProfile.bscanChain,
                sharedTwoWordFetchPmp = enabled, disjointEvictionStoreOverlap = enabled)
        built = Some(dut)
        dut
    }
    def hash(bytes: Array[Byte]): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes).map(b => f"${b & 255}%02x").mkString
    def fileHash(path: Path): String = hash(Files.readAllBytes(path))
    Files.createDirectories(out)
    if (mode == "native") {
        ChiselStage.emitSystemVerilogFile(construct(), Array("--target-dir", out.toString),
            Array("--strip-debug-info", "--disable-all-randomization", "--default-layer-specialization=disable"))
        require(Files.isRegularFile(out.resolve("FpgaNextSocTop.sv")))
        val rtlStream = Files.walk(out)
        val rtl = try rtlStream.iterator.asScala.filter(Files.isRegularFile(_))
            .filter(p => p.toString.endsWith(".sv") || p.toString.endsWith(".v"))
            .map(out.relativize(_).toString).toSeq.sorted finally rtlStream.close()
        require(rtl.nonEmpty)
        Files.writeString(out.resolve("filelist.f"), rtl.mkString("", "\n", "\n"))
    } else {
        val fir = ChiselStage.emitCHIRRTL(construct())
        Files.writeString(out.resolve("FpgaNextSocTop.fir"), fir)
        Files.writeString(out.resolve("FpgaNextSocTop.hardware.fir"), fir.replaceAll(" @\\[[^\\n]*?\\]", ""))
    }
    val actual = CombinedBandwidthNativeAudit.capture(built.get, c, enabled)
    // Enumerate exactly what the emitter produced, before adding audit/entry manifests.
    val stream = Files.walk(out)
    val generated = try stream.iterator.asScala.filter(Files.isRegularFile(_)).toSeq.sortBy(_.toString)
        finally stream.close()
    val inventory = ujson.Obj("schema" -> "combined-bandwidth-rtl-inventory-v1", "files" -> ujson.Obj.from(
        generated.map(path => out.relativize(path).toString -> ujson.Obj(
            "sha256" -> fileHash(path), "bytes" -> Files.size(path)))))
    Files.writeString(out.resolve("rtl-inventory.json"), inventory.render(indent = 2) + "\n")
    Files.writeString(out.resolve("actual-combined-native.json"), PostedBoardConfiguration.json(actual) + "\n")
    PostedBoardConfiguration.write(c, out.toString)
    Files.writeString(out.resolve("actual-core-parameters.json"), PostedBoardConfiguration.json(c.coreParams) + "\n")
    Files.writeString(out.resolve("actual-product-field-order.json"), PostedBoardConfiguration.json(
        Map("core" -> c.coreParams.productElementNames.toSeq, "profile" -> c.productElementNames.toSeq)) + "\n")
    Files.writeString(out.resolve("native-entry.json"), ujson.Obj(
        "schema" -> "combined-bandwidth-experimental-native-entry-v1",
        "identity" -> "combined-bandwidth-native-experimental", "mode" -> mode,
        "configurationBasis" -> "ThreeProofRowNativeProfile explicit constructor; independent experimental evidence",
        "coreFields" -> 178, "profileFields" -> 95, "nativeTopPorts" -> 76,
        "qualificationInherited" -> false, "physicalQualification" -> false,
        "nativeMacPhysicalGenericsApplied" -> false,
        "rtlInventorySha256" -> fileHash(out.resolve("rtl-inventory.json")),
        "actualAuditSha256" -> fileHash(out.resolve("actual-combined-native.json")),
        "scalaVersion" -> scala.util.Properties.versionNumberString).render(indent = 2) + "\n")
    println(s"PASS_COMBINED_BANDWIDTH_NATIVE mode=$mode shared_pmp=$enabled cache_overlap=$enabled rank=true core=178 profile=95 ports=76 UNQUALIFIED")
}
