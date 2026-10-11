package ooo

import _root_.circt.stage.ChiselStage
import chisel3.{Data, Vec}
import java.lang.reflect.{Field, Modifier}
import java.nio.file.{Files, Paths}
import scala.collection.mutable.ArrayBuffer
import soc.core.ooo._

/** Actual two-way cache/home gate. Both modes retain split tracking and identical
  * resources; only default-OFF demand adoption differs; posted kind encoding is enabled.
  */
object ReadPrefetchDemandAdoptionGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)),
        "output directory and explicit demand adoption 0|1 required")
    private val enabled = args(1) == "1"
    private val ways = 2
    private val expected = CoherentCacheConcurrency(readMshrs = 2, responseEntries = 2,
        writebackEntries = 2, overlapWritebackRefill = true, nextLinePrefetch = true,
        prefetchCandidateCycles = 16, prefetchBreakOnStore = false, storeNextLinePrefetch = true,
        storePrefetchMruInsertion = true, postedPrefetchCoexistence = true,
        storePrefetchLruVictim = false, independentDemandAdmission = true,
        splitPrefetchTracking = true, readPrefetchDirtyRetry = true, readPrefetchDemandAdoption = enabled)
    private val ramBase = BigInt("1000080010000", 16)
    private val ramBytes = BigInt(128 * 1024)

    private def fields(instance: AnyRef): Seq[Field] = {
        val result = ArrayBuffer.empty[Field]
        var declaring: Class[_] = instance.getClass
        while (declaring != null) {
            result ++= declaring.getDeclaredFields.filterNot(f => Modifier.isStatic(f.getModifiers))
            declaring = declaring.getSuperclass
        }
        result.toSeq
    }
    private def read(instance: AnyRef, field: Field): Any = {
        field.setAccessible(true)
        field.get(instance)
    }
    private def unique[T](instance: AnyRef, kind: Class[T]): T = {
        val matches = fields(instance).filter(_.getType == kind)
        require(matches.size == 1, s"${instance.getClass.getName} requires exactly one ${kind.getName}")
        kind.cast(read(instance, matches.head))
    }
    private def named(instance: AnyRef, name: String): Any = {
        val matches = fields(instance).filter(f => f.getName == name || f.getName.endsWith("$$" + name))
        require(matches.size == 1, s"${instance.getClass.getName} requires one actual field $name")
        read(instance, matches.head)
    }
    private def length(instance: AnyRef, name: String): Int =
        named(instance, name).asInstanceOf[Vec[Data]].length
    private def json(value: Any): String = value match {
        case text: String => "\"" + text.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
        case bool: Boolean => bool.toString
        case number: BigInt => number.toString
        case number: Int => number.toString
        case entries: collection.Map[_, _] => entries.toSeq.sortBy(_._1.toString)
            .map { case (key, item) => json(key.toString) + ":" + json(item) }.mkString("{", ",", "}")
        case product: Product => json(product.productElementNames.zip(product.productIterator).toMap)
        case other => throw new IllegalArgumentException("unsupported actual audit value " + other)
    }

    private var constructed = 0
    private var report: Option[Map[String, Any]] = None
    ChiselStage.emitCHIRRTLFile({
        constructed += 1
        require(constructed == 1, "actual component must be constructed exactly once")
        val top = new CoherentCacheHomeGsim(mshrs = 2, lines = 512,
            responseEntries = 2, compactTags = true, writebacks = 2, mixed = true,
            axiSlots = 4, unordered = true, prefetch = true, bankedTags = true,
            prefetchCandidateCycles = 16, testBase = ramBase,
            storeNextLinePrefetch = true, observeStorePrefetch = true,
            storePrefetchMruInsertion = true, storePrefetchLruVictim = false,
            splitPrefetchTracking = true, cacheWays = ways, independentDemandAdmission = true,
            readPrefetchDirtyRetry = true, readPrefetchDemandAdoption = enabled, demandAdoptionTest = true, postedPrefetchCoexistence = true)
        val cache = top.cache.asInstanceOf[NonBlockingCoherentLineCache]
        val home = top.home.asInstanceOf[MixedCoherentLineHome]
        val actual = unique(cache, classOf[CoherentCacheConcurrency])
        require(actual == expected, "actual cache policy/resource fields differ")
        val cacheGeometry = unique(cache, classOf[CacheTagGeometry])
        val homeGeometry = unique(home, classOf[CacheTagGeometry])
        val geometry = CacheTagGeometry(ramBase, ramBytes, if (ways == 2) 14 else 15, 64, compact = true)
        val expectedHomeGeometry = CacheTagGeometry(ramBase, ramBytes, 14, 64, compact = true)
        require(cacheGeometry == geometry && homeGeometry == expectedHomeGeometry,
            "actual cache/home aperture differs")
        val cacheWays = named(cache, "tagBanks").asInstanceOf[Option[Seq[Any]]].get.size
        val homeWays = named(home, "tagBanks").asInstanceOf[Seq[Any]].size
        val cacheLines = length(cache, "valid")
        val homeLines = length(home, "owned")
        val acquireEntries = length(home, "phase")
        val writebackEntries = length(home, "releasePhases")
        val cacheMshrs = length(cache, "phase")
        val cacheResponses = length(cache, "responseComplete")
        val cacheWritebacks = length(cache, "wbLive")
        require(cacheWays == ways && homeWays == 2 && cacheLines == 512 && homeLines == 512 &&
            acquireEntries == 2 && writebackEntries == 2 && cacheMshrs == 2 &&
            cacheResponses == 2 && cacheWritebacks == 2, "actual cache/home owner geometry differs")
        require(cache.io.posted.nonEmpty && cache.observationPosted.nonEmpty &&
            cache.observationPosted.get.refillEvent.context.owner.generation.getWidth == 64,
            "actual cache must enable board-width posted transaction identity")
        val obs = cache.observationStorePrefetch
        require(obs.readTokenAddress.getWidth == 64 && obs.storeTokenAddress.getWidth == 64 &&
            obs.readTokenIndex.getWidth == 9 && obs.storeTokenIndex.getWidth == 9 &&
            obs.readTokenValid.getWidth == 1 && obs.storeTokenValid.getWidth == 1,
            "qualification token identity must retain full PA and resident index")
        report = Some(Map("schema" -> "read-prefetch-demand-adoption-actual-component-v1",
            "mode" -> (if (enabled) "on" else "off"), "constructions" -> constructed,
            "cacheClass" -> cache.getClass.getName, "homeClass" -> home.getClass.getName,
            "cacheConcurrency" -> actual, "cacheTagConfig" -> top.tags,
            "postedConfig" -> named(top, "postedCfg").asInstanceOf[Option[PostedStoreMergeConfig]].get,
            "cacheGeometry" -> cacheGeometry, "homeGeometry" -> homeGeometry,
            "cacheLines" -> cacheLines, "cacheWays" -> cacheWays,
            "cacheMshrs" -> cacheMshrs, "cacheResponses" -> cacheResponses,
            "cacheWritebacks" -> cacheWritebacks, "homeTrackedLines" -> homeLines,
            "homeTrackedWays" -> homeWays, "homeAcquireEntries" -> acquireEntries,
            "homeWritebackEntries" -> writebackEntries, "axiSlots" -> 4,
            "postedEnabled" -> true, "postedGenerationBits" -> 64,
            "additionalSequentialHistoryBitsSpecified" -> 0,
            "additionalOwnerOrTokenBitsSpecified" -> (if (enabled) 4 else 0),
            "physicalResourceQualification" -> false, "executingCpu" -> false,
            "qualificationInherited" -> false))
        top
    }, Array("--target-dir", args(0)))
    require(constructed == 1 && report.nonEmpty, "actual constructor audit did not run")
    Files.writeString(Paths.get(args(0), "actual-parameters.json"), json(report.get) + "\n")
}
