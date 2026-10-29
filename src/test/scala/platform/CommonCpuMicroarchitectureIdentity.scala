package platform

import java.nio.charset.StandardCharsets
import java.nio.file.{Files, Path, Paths, StandardOpenOption}
import java.security.MessageDigest
import scala.jdk.CollectionConverters._
import soc.core.ooo.FpgaNextConfig
import soc.platform._

/** Export/cache identity, not hardware or a timing certificate. Parameter leaves
  * are strings; schema alone is numeric. This avoids cross-language integer and
  * floating-point JSON normalization changing an otherwise identical identity.
  */
object CommonCpuMicroarchitectureIdentity {
    /** A candidate must execute exactly the classes produced from these complete
      * compile inputs. This is separate from the microarchitecture/cache digest:
      * an old successful compile is not authority to emit a new candidate.
      */
    def verifyCompileReceipt(path: Path, root: Path): ujson.Value = {
        val receipt = ujson.read(Files.readString(path))
        require(receipt.obj.get("schema").contains(ujson.Str("valence-scala-compile-v1")) &&
            receipt.obj.get("exit").contains(ujson.Num(0)),
            "complete successful bound compile receipt required; legacy exit-only rejected")
        val sourceRoot = root.toAbsolutePath.normalize
        require(receipt("sourceRoot").str == sourceRoot.toString, "compile source root mismatch")
        val process = new ProcessBuilder("git", "rev-parse", "HEAD").directory(sourceRoot.toFile).start()
        val commit = new String(process.getInputStream.readAllBytes(), StandardCharsets.UTF_8).trim
        require(process.waitFor() == 0 && receipt("sourceCommit").str == commit, "compile source commit mismatch")
        def walk(directory: Path): Seq[Path] = if (!Files.isDirectory(directory)) Seq.empty else {
            val stream = Files.walk(directory)
            try stream.iterator.asScala.filter(Files.isRegularFile(_)).toVector finally stream.close()
        }
        def normalized(entry: Path): Path = if (Files.exists(entry)) entry.toRealPath() else entry.toAbsolutePath.normalize
        def sha(entry: Path): String = {
            val digest = MessageDigest.getInstance("SHA-256")
            val input = Files.newInputStream(entry)
            val bytes = new Array[Byte](1024 * 1024)
            try { var count = input.read(bytes); while (count >= 0) {
                if (count > 0) digest.update(bytes, 0, count)
                count = input.read(bytes)
            } } finally input.close()
            digest.digest.map(b => f"${b & 255}%02x").mkString
        }
        def hashes(entries: Seq[Path]): Map[String, String] = entries.map(entry =>
            normalized(entry).toString -> sha(entry)).toMap
        def readHashes(entry: ujson.Value): Map[String, String] = entry.obj.toMap.map {
            case (name, hash) => name -> hash.str
        }
        val scalaRoots = Seq("src/main/scala", "src/test/scala", "third_party/berkeley-hardfloat/src/main/scala")
        val resourceRoots = Seq("src/main/resources", "src/test/resources", "compile-resources",
            "third_party/berkeley-hardfloat/src/main/resources", "third_party/berkeley-hardfloat/compile-resources")
        val inputs = scalaRoots.flatMap(name => walk(sourceRoot.resolve(name)).filter(_.toString.endsWith(".scala"))) ++
            resourceRoots.flatMap(name => walk(sourceRoot.resolve(name))) ++
            Seq("build.mill", ".mill-version", ".mill-jvm-opts").map(sourceRoot.resolve(_))
        val sources = hashes(inputs)
        require(readHashes(receipt("sourceInputs")) == sources, "compile source set/hash mismatch")
        val manifest = receipt("sourceManifest")
        require(manifest.obj.keySet == Set("path", "sha256"), "compile source manifest binding missing")
        val manifestPath = Paths.get(manifest("path").str)
        require(sha(manifestPath) == manifest("sha256").str &&
            readHashes(ujson.read(Files.readString(manifestPath))) == sources, "compile source manifest mismatch")
        val classpath = sys.props("java.class.path").split(java.io.File.pathSeparator).toSeq.map(entry =>
            normalized(Paths.get(entry)))
        require(receipt("runClasspathEntries").arr.map(_.str).toSeq == classpath.map(_.toString),
            "post-compile runtime classpath entry/order mismatch")
        val classes = hashes(classpath.flatMap(entry => if (Files.isDirectory(entry)) walk(entry)
            else if (Files.isRegularFile(entry)) Seq(entry) else Seq.empty))
        require(classes.nonEmpty && readHashes(receipt("compiledClasspath")) == classes,
            "post-compile runtime classpath set/hash mismatch")
        receipt
    }

    def value(entry: Any): ujson.Value = entry match {
        case null => ujson.Null
        case option: Option[_] => option.map(value).getOrElse(ujson.Null)
        case text: String => ujson.Str(text)
        case number: BigInt => ujson.Str(number.toString)
        case entries: scala.collection.Map[_, _] =>
            ujson.Obj.from(entries.toSeq.map { case (key, item) => key.toString -> value(item) }.sortBy(_._1))
        case entries: Seq[_] => ujson.Arr.from(entries.map(value))
        case product: Product if product.productArity > 0 =>
            ujson.Obj.from(product.productElementNames.zip(product.productIterator).map {
                case (key, item) => key -> value(item)
            }.toSeq.sortBy(_._1))
        case product: Product => ujson.Str(product.productPrefix)
        case scalar => ujson.Str(scalar.toString)
    }

    private def canonical(entry: ujson.Value): ujson.Value = entry match {
        case obj: ujson.Obj => ujson.Obj.from(obj.value.toSeq.sortBy(_._1).map {
            case (key, item) => key -> canonical(item)
        })
        case array: ujson.Arr => ujson.Arr.from(array.value.map(canonical))
        case scalar => scalar
    }
    def digest(entry: ujson.Value): String = MessageDigest.getInstance("SHA-256")
        .digest(ujson.write(canonical(entry), indent = -1, escapeUnicode = false).getBytes(StandardCharsets.UTF_8))
        .map(b => f"${b & 255}%02x").mkString

    private def configuration(config: FpgaNextConfig): ujson.Value = {
        val fields = value(config).obj
        fields("_derived") = ujson.Obj(
            "isaProfile" -> value(config.isaProfile), "issueWidth" -> value(config.issueWidth),
            "ramBase" -> value(config.ramBase), "ddrBytes" -> value(config.ddrBytes),
            "cacheLineBytes" -> value(config.cacheLineBytes),
            "instructionCacheLines" -> value(config.instructionCacheLines),
            "dataCacheLines" -> value(config.dataCacheLines), "cacheWays" -> value(config.cacheWays),
            "ddr" -> value(config.ddr), "cache" -> value(config.cache), "tags" -> value(config.tags),
            "network" -> value(config.network), "storage" -> value(config.storage),
            "floatingPointResources" -> value(config.floatingPointResources))
        ujson.Obj.from(fields)
    }

    def build(profile: CommonCpuProfile, selected: Option[CommonA1ExperimentalSelection],
        boundary: CommonCpuTilePortParams, experimentalRuntime: Boolean = false,
        cpuSpec: Option[CommonA1CpuSpec] = None): ujson.Obj = {
        val config = CommonA1CpuSpec.resolve(profile, selected, cpuSpec, boundary, experimentalRuntime)
        val result = ujson.Obj(
            "schema" -> 1,
            "cpuFamily" -> profile.kind,
            "microarchitectureProfile" -> ujson.Str(cpuSpec.map(_.name).orElse(selected.map(_.name)).getOrElse(
                if (profile.kind == "a1") "selected" else "public-i1")),
            "qualification" -> (if (cpuSpec.nonEmpty) "EXPLICIT_CPU_SPEC_NOT_CPU_BEHAVIOR_QUALIFIED"
                else if (selected.nonEmpty) "EXPERIMENTAL_NOT_TIMING_QUALIFIED"
                else "PUBLIC_UNCHANGED_NOT_TIMING_QUALIFIED"),
            "effectiveConfig" -> configuration(config),
            "effectiveCore" -> (if (profile.kind == "a1") value(config.coreParams) else value(profile.i1)),
            "memoryProfile" -> value(CommonA1ExperimentalSelection.memoryProfile(selected).map(_.name)),
            "boundary" -> value(boundary),
            "sharedFabricConfig" -> configuration(profile.fpga),
            "clockProfile" -> profile.clockProfile,
            "nominalClocks" -> ujson.Obj(
                "cpuHz" -> value(profile.cpuHz), "fabricHz" -> value(profile.fabricHz),
                "timebaseHz" -> value(profile.clocks.timebaseHz), "ddrUiHz" -> value(profile.ddrUiHz),
                "aonHz" -> value(profile.aonHz), "uartHz" -> value(profile.uartHz)),
            "runtimeMode" -> (if (experimentalRuntime) "experimental-a1-runtime"
                else if (profile.clockProfile == "boot50-dynamic") "public-i1-runtime" else "static"))
        cpuSpec.foreach { spec =>
            // v1's implicit 16/48 and v2's explicit 16/48 describe the same CPU.
            // Preserve the old one-field shape; input-file provenance is separate.
            val requested = ujson.Obj("lsuOwners" -> value(spec.lsuOwners))
            if (spec.robEntries != 16 || spec.physicalRegs != 48) {
                requested("robEntries") = value(spec.robEntries)
                requested("physicalRegs") = value(spec.physicalRegs)
            }
            result("requestedCpuSpec") = requested
        }
        result("identitySha256") = digest(result)
        result
    }

    def write(path: Path, identity: ujson.Value): Unit = {
        Files.writeString(path, ujson.write(canonical(identity), indent = 2) + "\n", StandardCharsets.UTF_8,
            StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)
    }
}
