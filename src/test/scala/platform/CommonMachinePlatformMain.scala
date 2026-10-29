package platform

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path, Paths, StandardOpenOption}
import java.security.MessageDigest
import scala.jdk.CollectionConverters._
import soc.platform._

/** Explicit production geometry exporter. Programmable ROM is for native
  * verification only; the same emitted model can load the guest and full TUI
  * image. CPU specifications and peripheral composition are explicit bounded choices.
  */
object CommonMachinePlatformMain extends App {
    require(args.length >= 3, "output, i1|a1|--soc-config=FILE, and --compile-receipt=... required")
    val output = Paths.get(args(0)).toAbsolutePath.normalize
    require(!Files.exists(output), "fresh output directory required")
    val options = args.drop(2)
    val configurationPath = if (args(1).startsWith("--soc-config="))
        Some(Paths.get(args(1).stripPrefix("--soc-config=")).toAbsolutePath.normalize) else None
    val configurationBytes = configurationPath.map(Files.readAllBytes(_))
    val configurationHash = configurationBytes.map(bytes => MessageDigest.getInstance("SHA-256")
        .digest(bytes).map(b => f"${b & 255}%02x").mkString)
    val socConfig = CommonSocConfigFile.select(args(1), options.toSeq,
        configurationBytes.map(bytes => new String(bytes, java.nio.charset.StandardCharsets.UTF_8)).getOrElse(""))
    val profile = socConfig.profile
    val clockProfile = profile.clockProfile
    val peripheralConfig = socConfig.peripherals
    val selected = socConfig.a1Experimental
    val cpuSpec = socConfig.cpuSpec
    val chirrtlOnly = options.contains("--emit-chirrtl-only")
    val dynamic = clockProfile == "boot50-dynamic"
    peripheralConfig.validateRuntime(dynamic)
    val diagnosticOption = "--diagnostic-rates=" + CommonDiagnosticRateProfile.option
    val diagnostic = options.contains(diagnosticOption)
    require(!diagnostic || dynamic, "diagnostic rates require boot50-dynamic")
    val legalFlags = Set("--programmable", "--vivado-memories", "--emit-chirrtl-only", diagnosticOption)
    require(options.forall(x => legalFlags(x) || x.startsWith("--compile-receipt=") ||
        x.startsWith("--clock-profile=") || x.startsWith("--experimental-a1-profile=") ||
        x.startsWith("--jtag-download=") || x.startsWith("--a1-lsu-owners=")))
    val compileReceipt = Paths.get(options.find(_.startsWith("--compile-receipt=")).get
        .stripPrefix("--compile-receipt=")).toAbsolutePath.normalize
    require(ujson.read(Files.readString(compileReceipt))("exit").num == 0,
        "successful compile receipt required before emission")
    val programmable = options.contains("--programmable")
    val vivado = options.contains("--vivado-memories")
    require(!dynamic || !programmable, "dynamic board profile has no unhandshaked ROM-program source")
    require(programmable != vivado, "select explicit native-programmable or production-Vivado ROM")
    val boundary = if (dynamic) profile.boundary.copy(
        runtimeMaintenance = true, runtimeCancellation = true, runtimeInterruptHold = true) else profile.boundary
    val actualCpuConfig = socConfig.cpuConfig(boundary)
    val identity = CommonCpuMicroarchitectureIdentity.build(profile, selected, boundary, cpuSpec = cpuSpec)
    val root = Paths.get(sys.props.getOrElse("chisel.project.root", ".")).toAbsolutePath.normalize
    val compileBinding = if (selected.nonEmpty || cpuSpec.nonEmpty)
        Some(CommonCpuMicroarchitectureIdentity.verifyCompileReceipt(compileReceipt, root)) else None
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
    def platform() = new CommonMachinePlatform(profile, programmable = programmable,
        hardwareClocks = true, vivadoMemories = vivado,
        independentDdrClock = profile.independentFixedDomains,
        independentTimebaseClock = profile.independentFixedDomains,
        independentDebugClock = profile.independentFixedDomains,
        runtimeDebugAdmission = dynamic, runtimeNetworkAdmission = dynamic,
        runtimeFixedQualification = dynamic, runtimeControlQualification = dynamic,
        runtimeFixedMac = dynamic, runtimeRateControl = dynamic, externalIrqsAbsent = dynamic,
        diagnosticRateAdmission = diagnostic, performanceTelemetry = diagnostic, a1Experimental = selected,
        peripheralConfig = peripheralConfig, cpuSpec = cpuSpec)
    if (chirrtlOnly) ChiselStage.emitCHIRRTLFile(platform(), Array("--target-dir", output.toString))
    else ChiselStage.emitSystemVerilogFile(platform(), Array("--target-dir", output.toString),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            s"--lowering-options=$lowering",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
    require(configurationPath.map(sha) == configurationHash, "SoC configuration file changed during emission")
    require(hashes(sourcePaths) == sources, "source changed during emission")
    require(hashes(classPaths) == classes, "compiled classes changed during emission")
    compileBinding.foreach(binding => require(
        CommonCpuMicroarchitectureIdentity.verifyCompileReceipt(compileReceipt, root) == binding,
        "bound compile receipt changed during candidate emission"))
    CommonCpuMicroarchitectureIdentity.write(output.resolve("microarchitecture-identity.json"), identity)
    val artifacts = hashes(walk(output))
    def objectOf(m: Map[String, String]): ujson.Obj = ujson.Obj.from(m.toSeq.sortBy(_._1).map { case (k, v) => k -> ujson.Str(v) })
    val manifest = ujson.Obj(
        "schema" -> 1, "top" -> "CommonMachinePlatform", "cpu" -> profile.kind,
        "cpuMicroarchitectureProfile" -> identity("microarchitectureProfile"),
        "cpuQualification" -> identity("qualification"), "cpuMicroarchitecture" -> identity,
        "rtlFormat" -> (if (chirrtlOnly) "CHIRRTL" else "SystemVerilog"),
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
        "instructionCacheBytes" -> (if (profile.kind == "i1") profile.i1.instructionCacheBytes
            else actualCpuConfig.instructionCacheLines * actualCpuConfig.cacheLineBytes),
        "dataCacheBytes" -> (if (profile.kind == "i1") profile.i1.dataCacheBytes
            else actualCpuConfig.dataCacheLines * actualCpuConfig.cacheLineBytes),
        "cacheWays" -> (if (profile.kind == "i1") profile.i1.coherentCacheWays else actualCpuConfig.cacheWays),
        "tlbEntries" -> (if (profile.kind == "i1") profile.i1.tlbEntries else actualCpuConfig.dataTranslationEntries),
        "issueWidth" -> (if (profile.kind == "i1") 1 else actualCpuConfig.issueWidth),
        "a1Resources" -> (if (profile.kind == "a1") ujson.Obj(
            "robEntries" -> actualCpuConfig.coreParams.robEntries,
            "physicalRegisters" -> actualCpuConfig.coreParams.physicalRegs,
            "lsuOwners" -> actualCpuConfig.coreParams.memoryEntries,
            "storeBufferEntries" -> actualCpuConfig.coreParams.storeBufferEntries) else ujson.Null),
        "homeClients" -> 2, "homeLines" -> 1024, "homeWays" -> 4,
        "homeAcquireEntries" -> 2, "homeWritebackEntries" -> 2,
        "ddrSlots" -> profile.fpga.ddr.maxOutstanding, "ddrWriteSlots" -> profile.fpga.ddr.maxOutstandingWrites,
        "heldFifo" -> "HeldResponseCdcDataFifo", "fifoDepth" -> 16,
        "triSpeedEthernet" -> true, "triSpeedTxFrameSlots" -> 2,
        "jtagDownload" -> peripheralConfig.jtagDownload,
        "jtagDmiAddressBits" -> (if (peripheralConfig.jtagDownload) ujson.Num(7) else ujson.Null),
        "peripheralQualification" -> "configuration-only-not-new-behavior-or-timing-qualification",
        "cpuMmioRegions" -> ujson.Arr.from(peripheralConfig.mmioRegions.map(r => ujson.Obj(
            "name" -> r.name, "base" -> ("0x" + r.base.toString(16)), "bytes" -> r.bytes.toString))),
        "externalHotMaintenanceSupported" -> false, "oneSidedResetSupported" -> false,
        "physicalTimingVerified" -> false, "boardVerified" -> false,
        "sources" -> objectOf(sources), "compiledClasspath" -> objectOf(classes),
        "artifacts" -> objectOf(artifacts))
    // Configuration/provenance report, not an architectural identity or a new
    // CPU behavior/performance qualification. Effective fields reuse the same
    // resolved values as emission-profile; there is no second sizing table.
    val resolved = ujson.Obj(
        "schema" -> 1, "purpose" -> "resolved-soc-configuration-not-performance-qualification",
        "requested" -> CommonSocConfigFile.requested(socConfig),
        "configurationFile" -> configurationPath.map(p => ujson.Str(p.toString)).getOrElse(ujson.Null),
        "configurationSha256" -> configurationHash.map(ujson.Str(_)).getOrElse(ujson.Null),
        "effective" -> ujson.Obj.from(Seq("cpu", "clockProfile", "cpuMicroarchitectureProfile", "cpuQualification",
            "cpuClockHz", "fabricClockHz", "timebaseHz", "instructionCacheBytes", "dataCacheBytes", "cacheWays",
            "issueWidth", "a1Resources", "homeClients", "homeLines", "homeWays", "ddrSlots", "ddrWriteSlots",
            "jtagDownload", "jtagDmiAddressBits", "cpuMmioRegions", "abi").map(k => k -> manifest(k))),
        "cpuIdentitySha256" -> identity("identitySha256"),
        "physicalTimingVerified" -> false, "boardVerified" -> false)
    Files.writeString(output.resolve("resolved-soc-config.json"), ujson.write(resolved, indent = 2) + "\n",
        StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)
    manifest("artifacts") = objectOf(hashes(walk(output)))
    Files.writeString(output.resolve("emission-profile.json"), ujson.write(manifest, indent = 2) + "\n",
        StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)
}
