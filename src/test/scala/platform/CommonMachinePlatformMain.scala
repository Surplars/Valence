package platform

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path, Paths, StandardOpenOption}
import java.security.MessageDigest
import scala.jdk.CollectionConverters._
import soc.platform._

/** Explicit production geometry exporter. Programmable ROM is for native
  * verification only; the same emitted model can load the guest and full TUI
  * image. No reduced CPU/cache/owner or replacement peripheral profile exists.
  */
object CommonMachinePlatformMain extends App {
    require(args.length >= 3, "output, i1|a1, and --compile-receipt=... required")
    val output = Paths.get(args(0)).toAbsolutePath.normalize
    require(!Files.exists(output), "fresh output directory required")
    val options = args.drop(2)
    val clockProfile = options.find(_.startsWith("--clock-profile=")).map(_.stripPrefix("--clock-profile=")).getOrElse("production")
    val profile = CommonCpuProfile.named(args(1), clockProfile)
    val dynamic = clockProfile == "boot50-dynamic"
    val diagnosticOption = "--diagnostic-rates=" + CommonDiagnosticRateProfile.option
    val diagnostic = options.contains(diagnosticOption)
    require(!diagnostic || dynamic, "diagnostic rates require boot50-dynamic")
    val legalFlags = Set("--programmable", "--vivado-memories", diagnosticOption)
    require(options.forall(x => legalFlags(x) || x.startsWith("--compile-receipt=") || x.startsWith("--clock-profile=")))
    require(options.map(_.takeWhile(_ != '=')).distinct.length == options.length)
    val compileReceipt = Paths.get(options.find(_.startsWith("--compile-receipt=")).get
        .stripPrefix("--compile-receipt=")).toAbsolutePath.normalize
    require(ujson.read(Files.readString(compileReceipt))("exit").num == 0,
        "successful compile receipt required before emission")
    val programmable = options.contains("--programmable")
    val vivado = options.contains("--vivado-memories")
    require(!dynamic || !programmable, "dynamic board profile has no unhandshaked ROM-program source")
    require(programmable != vivado, "select explicit native-programmable or production-Vivado ROM")
    val root = Paths.get(sys.props.getOrElse("chisel.project.root", ".")).toAbsolutePath.normalize
    def walk(directory: Path): Seq[Path] = {
        val stream = Files.walk(directory)
        try stream.iterator.asScala.filter(Files.isRegularFile(_)).toSeq finally stream.close()
    }
    def sha(path: Path): String = {
        val digest = MessageDigest.getInstance("SHA-256")
        val stream = Files.newInputStream(path)
        val bytes = new Array[Byte](1024 * 1024)
        try { var n = stream.read(bytes); while (n >= 0) { if (n > 0) digest.update(bytes, 0, n); n = stream.read(bytes) } }
        finally stream.close()
        digest.digest.map(b => f"${b & 255}%02x").mkString
    }
    val sourcePaths = (walk(root.resolve("src/main/scala")) ++ walk(root.resolve("src/test/scala/platform")))
        .filter(_.toString.endsWith(".scala")) ++ Seq(root.resolve("build.mill"), compileReceipt)
    val classPaths = sys.props("java.class.path").split(java.io.File.pathSeparator).toSeq.map(Paths.get(_))
        .flatMap(p => if (Files.isDirectory(p)) walk(p) else Seq(p)).filter(Files.isRegularFile(_))
    def hashes(paths: Seq[Path]): Map[String, String] = paths.map(p => p.toAbsolutePath.normalize.toString -> sha(p)).toMap
    val sources = hashes(sourcePaths)
    val classes = hashes(classPaths)
    // firtool 1.135 optimizes the public A1 fetch mux into a packed array;
    // forbidding that legal SV form fails during export. Keep normal packed
    // output for A1 (Icarus supports it); no DUT architecture is changed.
    val lowering = if (profile.kind == "a1") "disallowLocalVariables"
        else "disallowLocalVariables,disallowPackedArrays"
    ChiselStage.emitSystemVerilogFile(new CommonMachinePlatform(profile, programmable = programmable,
        hardwareClocks = true, vivadoMemories = vivado,
        independentDdrClock = profile.independentFixedDomains,
        independentTimebaseClock = profile.independentFixedDomains,
        independentDebugClock = profile.independentFixedDomains,
        runtimeDebugAdmission = dynamic, runtimeNetworkAdmission = dynamic,
        runtimeFixedQualification = dynamic, runtimeControlQualification = dynamic,
        runtimeFixedMac = dynamic, runtimeRateControl = dynamic, externalIrqsAbsent = dynamic,
        diagnosticRateAdmission = diagnostic, performanceTelemetry = diagnostic), Array("--target-dir", output.toString),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            s"--lowering-options=$lowering",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
    require(hashes(sourcePaths) == sources, "source changed during emission")
    require(hashes(classPaths) == classes, "compiled classes changed during emission")
    val artifacts = hashes(walk(output))
    def objectOf(m: Map[String, String]): ujson.Obj = ujson.Obj.from(m.toSeq.sortBy(_._1).map { case (k, v) => k -> ujson.Str(v) })
    val manifest = ujson.Obj(
        "schema" -> 1, "top" -> "CommonMachinePlatform", "cpu" -> profile.kind,
        "clockProfile" -> profile.clockProfile, "runtimeClockReconfiguration" -> dynamic,
        "functionalProfile" -> (if (diagnostic) "boot50-dynamic-software-parameter-diagnostic" else profile.clockProfile),
        "rateAdmission" -> (if (diagnostic) "explicit-diagnostic-not-qualified" else "qualified-only"),
        "softwareParameterMode" -> diagnostic,
        "clockRateAbi" -> (if (diagnostic) 2 else 1),
        "performanceTelemetryAbi" -> (if (diagnostic) 1 else 0),
        "hardwareRateWhitelist" -> false,
        "rateParameterEncoding" -> (if (diagnostic) "D[7:0],M[15:8],O[23:16]; upper bits zero" else "absent"),
        "rateParameterLimits" -> (if (diagnostic) ujson.Obj("D" -> 10, "minM" -> 32, "maxM" -> 62,
            "minO" -> 3, "maxO" -> 128, "referenceHz" -> 250000000,
            "minimumHz" -> 10000000, "maximumCpuHz" -> 300000000, "maximumFabricHz" -> 250000000)
            else ujson.Obj()),
        "qualifiedRatePointsHz" -> ujson.Arr(),
        "diagnosticPointFlags" -> (if (diagnostic) 48 else 0),
        "performanceTelemetry" -> diagnostic,
        "frequencyMeasurement" -> (if (diagnostic) "managed-edge-count-over-aon-window" else "absent"),
        "telemetryBase" -> (if (diagnostic) "0x10080900" else "absent"),
        "independentFixedDomains" -> profile.independentFixedDomains,
        "clockTopology" -> (if (profile.independentFixedDomains) "independent-fixed-v1" else "legacy-ui-fabric"),
        "clockProfilePurpose" -> (if (profile.clockProfile == "performance300-static") "high-frequency-timing-target"
            else if (profile.clockProfile == "boot50-static") "low-frequency-board-candidate"
            else if (diagnostic) "dynamic-clock-functional-diagnostic-candidate-not-timing-qualified"
            else if (dynamic) "dynamic-clock-integration-candidate-empty-rate-table" else "legacy-production"),
        "abi" -> 1, "romBytes" -> CommonPlatformAbi.romBytes,
        "programmableRom" -> programmable, "vivadoMemories" -> vivado,
        "hardwareClocks" -> true, "independentCpuFabricClocks" -> true,
        "loweringOptions" -> lowering,
        "cpuClockHz" -> profile.cpuHz, "fabricClockHz" -> profile.fabricHz,
        "timebaseHz" -> profile.clocks.timebaseHz, "ddrUiHz" -> profile.ddrUiHz,
        "aonHz" -> profile.aonHz, "uartHz" -> profile.uartHz, "uartBaud" -> profile.uartBaud,
        "instructionCacheBytes" -> 32768, "dataCacheBytes" -> 32768, "cacheWays" -> 2,
        "tlbEntries" -> (if (profile.kind == "i1") profile.i1.tlbEntries else profile.fpga.dataTranslationEntries),
        "issueWidth" -> (if (profile.kind == "i1") 1 else 2),
        "homeClients" -> 2, "homeLines" -> 1024, "homeWays" -> 4,
        "homeAcquireEntries" -> 2, "homeWritebackEntries" -> 2,
        "ddrSlots" -> profile.fpga.ddr.maxOutstanding, "ddrWriteSlots" -> profile.fpga.ddr.maxOutstandingWrites,
        "heldFifo" -> "HeldResponseCdcDataFifo", "fifoDepth" -> 16,
        "triSpeedEthernet" -> true, "triSpeedTxFrameSlots" -> 2, "jtagDmiAddressBits" -> 7,
        "externalHotMaintenanceSupported" -> false, "oneSidedResetSupported" -> false,
        "physicalTimingVerified" -> false, "boardVerified" -> false,
        "sources" -> objectOf(sources), "compiledClasspath" -> objectOf(classes),
        "artifacts" -> objectOf(artifacts))
    Files.writeString(output.resolve("emission-profile.json"), ujson.write(manifest, indent = 2) + "\n",
        StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)
}
