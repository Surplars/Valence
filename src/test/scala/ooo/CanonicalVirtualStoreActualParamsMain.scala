package ooo

import _root_.circt.stage.ChiselStage
import java.lang.reflect.{Field, Modifier}
import java.nio.file.{Files, Paths}
import scala.collection.mutable.ArrayBuffer
import soc.bus.tilelink.TLParams
import soc.core.ooo._

/** Read-only elaboration audit of the final instantiated modules.
  * Reflection reads existing constructor fields; it creates no ports, nodes or
  * hardware. This is the same production top and config parser used by FpgaNextMain.
  * Native graph/source correspondence is independently checked before reusing any qualification.
  */
/** Shared read-only audit; entry-point wrappers choose explicit experiment profiles. */
final class CanonicalVirtualStoreActualParamsAudit(
    profile: FpgaNextConfig,
    output: String,
    mode: String,
    referenceOptions: Set[String],
    experiment: String = "canonical-virtual-store-official-entry"
) {
    private val outputDirectory = Paths.get(output)
    require(profile == FpgaNextConfig.fromOptions(referenceOptions, defaultSelected = false),
        "audit entry profile differs from explicit native options")
    require(profile.canonicalVirtualStoreOverlap == (mode == "on"), "official treatment differs from side")
    private val expectedCore = profile.coreParams
    require(expectedCore.productArity == 136 && expectedCore.memoryEntries == 4 &&
        expectedCore.robEntries == 16 && expectedCore.renameWidth == 2 && expectedCore.tagBits == 64 &&
        !expectedCore.fastBufferedStoreRetire && !expectedCore.precheckedDataRequestFlow &&
        !expectedCore.translatedResponseEmptyFlow && profile.dmaLineTransfers && profile.dmaLineEntries == 4)

    private def quote(value: String): String = "\"" + value.flatMap {
        case '"' => "\\\""
        case '\\' => "\\\\"
        case '\n' => "\\n"
        case '\r' => "\\r"
        case '\t' => "\\t"
        case character if character < ' ' => f"\\u${character.toInt}%04x"
        case character => character.toString
    } + "\""

    private def json(value: Any): String = value match {
        case null => "null"
        case text: String => quote(text)
        case bool: Boolean => bool.toString
        case number: BigInt => number.toString
        case number: Int => number.toString
        case number: Long => number.toString
        case option: Option[_] => option.map(json).getOrElse("null")
        case fields: collection.Map[_, _] => fields.toSeq.sortBy(_._1.toString)
            .map { case (name, item) => quote(name.toString) + ":" + json(item) }.mkString("{", ",", "}")
        case items: Seq[_] => items.map(json).mkString("[", ",", "]")
        case product: Product => json(product.productElementNames.zip(product.productIterator).toMap)
        case other => throw new IllegalArgumentException("unserialized audit value: " + other.getClass.getName)
    }

    /** Traverse every declaring class so shadowed constructor parameters are visible. */
    private def typedFields(instance: AnyRef, expectedType: Class[_]): Seq[Field] = {
        val result = ArrayBuffer.empty[Field]
        var declaring: Class[_] = instance.getClass
        while (declaring != null) {
            result ++= declaring.getDeclaredFields.filter(field =>
                !Modifier.isStatic(field.getModifiers) && field.getType == expectedType)
            declaring = declaring.getSuperclass
        }
        result.toSeq.sortBy(field => (field.getDeclaringClass.getName, field.getName))
    }

    private def read[T](instance: AnyRef, field: Field, expectedType: Class[T]): T = {
        field.setAccessible(true)
        val value = field.get(instance)
        require(value != null, s"null final parameter ${field.getDeclaringClass.getName}.${field.getName}")
        expectedType.cast(value)
    }

    private def unique[T](instance: AnyRef, expectedType: Class[T], path: String): (Field, T) = {
        val fields = typedFields(instance, expectedType)
        require(fields.size == 1,
            s"$path requires one ${expectedType.getName} field across its class hierarchy, found ${fields.size}")
        fields.head -> read(instance, fields.head, expectedType)
    }

    private def record(instance: AnyRef, path: String, field: Field, value: Any): Map[String, Any] =
        Map("instancePath" -> path, "actualClass" -> instance.getClass.getName,
            "declaringClass" -> field.getDeclaringClass.getName, "fieldName" -> field.getName,
            "fieldType" -> field.getType.getName, "values" -> value)

    private def audit(top: AnyRef): Map[String, Any] = {
        val (boardField, board) = unique(top, classOf[BoardSocTop], "top")
        val platform = board.platform
        val mapped = platform.core
        val machine = mapped.core
        val integer = machine.core
        val backend = integer.backend
        val modules: Seq[(String, AnyRef)] = Seq(
            "top.board" -> board,
            "top.board.platform" -> platform,
            "top.board.platform.core" -> mapped,
            "top.board.platform.core.core" -> machine,
            "top.board.platform.core.core.core" -> integer,
            "top.board.platform.core.core.core.backend" -> backend)
        val coreRecords = modules.map { case (path, instance) =>
            val (field, actual) = unique(instance, classOf[OooParams], path)
            require(actual.productArity == 136 && actual == expectedCore,
                s"actual final OooParams differs at $path (${field.getDeclaringClass.getName}.${field.getName})")
            record(instance, path, field, actual)
        }
        val cache = platform.privateCache.getOrElse(
            throw new IllegalArgumentException("audit requires actual private cache")) match {
            case actual: NonBlockingCoherentLineCache => actual
            case other => throw new IllegalArgumentException("audit requires nonblocking cache, got " + other.getClass.getName)
        }
        val ddrRecords = modules.take(2).map { case (path, instance) =>
            val (field, actual) = unique(instance, classOf[DdrBridgeConfig], path)
            require(actual == profile.ddr, s"actual DDR constructor differs at $path")
            record(instance, path, field, actual)
        }
        val cachePath = "top.board.platform.privateCache.get"
        val concurrencyRecords = (modules.take(2) :+ (cachePath -> cache)).map { case (path, instance) =>
            val (field, actual) = unique(instance, classOf[CoherentCacheConcurrency], path)
            require(actual == profile.cache, s"actual cache concurrency differs at $path")
            record(instance, path, field, actual)
        }
        val expectedTl = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 1, sizeBits = 3)
        val tlFields = typedFields(cache, classOf[TLParams])
        require(tlFields.nonEmpty, "actual cache TLParams field is absent")
        val tlRecords = tlFields.map { field =>
            val actual = read(cache, field, classOf[TLParams])
            require(actual == expectedTl,
                s"actual cache TLParams differs at ${field.getDeclaringClass.getName}.${field.getName}")
            record(cache, cachePath, field, actual)
        }
        Map("schema" -> "posted-board-actual-parameters-v1", "mode" -> mode, "experiment" -> experiment,
            "qualificationInherited" -> false,
            "topClass" -> top.getClass.getName,
            "boardField" -> Map("declaringClass" -> boardField.getDeclaringClass.getName,
                "fieldName" -> boardField.getName, "fieldType" -> boardField.getType.getName),
            "canonicalOptions" -> referenceOptions.toSeq.sorted,
            "officialTreatment" -> Map("canonicalVirtualStoreOverlap" -> (mode == "on"), "productionCliSupportsTreatment" -> true),
            "entryProfile" -> profile, "expectedCore" -> expectedCore,
            "coreParameters" -> coreRecords, "ddrParameters" -> ddrRecords,
            "cacheConcurrency" -> concurrencyRecords, "cacheTileLinkParameters" -> tlRecords,
            "allActualParametersEqualExpected" -> true,
            "hardwareMutation" -> false,
            "modelAuthority" -> "This single audited construction emits the actual model FIR")
    }

    private var generationCount = 0
    private var actualReport: Option[Map[String, Any]] = None
    ChiselStage.emitCHIRRTLFile({
        generationCount += 1
        require(generationCount == 1, "audit top must be constructed exactly once")
        val top = new FpgaNextSocTop(profile)
        actualReport = Some(audit(top))
        top
    }, Array("--target-dir", output))
    require(generationCount == 1 && actualReport.nonEmpty, "actual module audit did not execute")
    Files.createDirectories(outputDirectory)
    Files.writeString(outputDirectory.resolve("actual-parameters.json"), json(actualReport.get) + "\n")
}

/** Official native entry with read-only actual-parameter audit and CHIRRTL output. */
object CanonicalVirtualStoreActualParamsMain extends App {
    require(args.length >= 3 && Set("off", "on").contains(args(1)),
        "directory, explicit side and exact official native flags required")
    val mode = args(1)
    val options = args.drop(2).toSet
    val expected = PostedPrefetchBoardProfiles.options("head-offer", "on") ++
        (if (mode == "on") Set("--canonical-virtual-store-overlap") else Set.empty[String])
    require(options.size == args.length - 2 && options == expected, "official canonical options differ")
    val profile = FpgaNextConfig.fromOptions(options, defaultSelected = true)
    require(profile.productArity == 27 && profile.coreParams.productArity == 136)
    require(profile == PostedPrefetchBoardProfiles.profile("head-offer", "on")
        .copy(canonicalVirtualStoreOverlap = mode == "on"))
    require(!Files.exists(Paths.get(args(0))), "actual entry audit requires a fresh output directory")
    PostedBoardConfiguration.write(profile, args(0))
    new CanonicalVirtualStoreActualParamsAudit(profile, args(0), mode, options)
}
