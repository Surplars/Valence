package ooo

import _root_.circt.stage.ChiselStage
import chisel3.{Data, Vec}
import java.lang.reflect.{Field, Modifier}
import java.nio.file.{Files, Paths}
import scala.collection.mutable.ArrayBuffer
import soc.core.ooo._

/** Actual cache + Mixed home + AXI, with real full-width physical addresses.
  * Store prediction and MRU insertion remain enabled in both policy modes.
  * The audit reads constructed Scala objects; no extra hardware is emitted.
  */
object StorePrefetchLruVictimGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)),
        "output directory and explicit store PF LRU victim 0|1 required")
    private val enabled = args(1) == "1"
    private val expected = CoherentCacheConcurrency(readMshrs = 2, responseEntries = 2,
        writebackEntries = 2, overlapWritebackRefill = true, nextLinePrefetch = true,
        prefetchCandidateCycles = 1, prefetchBreakOnStore = false, storeNextLinePrefetch = true,
        storePrefetchMruInsertion = true, postedPrefetchCoexistence = false, storePrefetchLruVictim = enabled)
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
        case fields: collection.Map[_, _] => fields.toSeq.sortBy(_._1.toString)
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
            testBase = ramBase, storeNextLinePrefetch = true, observeStorePrefetch = true,
            storePrefetchMruInsertion = true, storePrefetchLruVictim = enabled)
        val cache = top.cache.asInstanceOf[NonBlockingCoherentLineCache]
        val home = top.home.asInstanceOf[MixedCoherentLineHome]
        val actual = unique(cache, classOf[CoherentCacheConcurrency])
        require(actual.productArity == 11 && actual == expected, "actual cache policy/resource fields differ")
        val cacheGeometry = unique(cache, classOf[CacheTagGeometry])
        val homeGeometry = unique(home, classOf[CacheTagGeometry])
        val geometry = CacheTagGeometry(ramBase, ramBytes, 14, 64, compact = true)
        require(cacheGeometry == geometry && homeGeometry == geometry, "actual cache/home aperture differs")
        val cacheWays = named(cache, "tagBanks").asInstanceOf[Option[Seq[Any]]].get.size
        val homeWays = named(home, "tagBanks").asInstanceOf[Seq[Any]].size
        val cacheLines = length(cache, "valid")
        val homeLines = length(home, "owned")
        val acquireEntries = length(home, "phase")
        val writebackEntries = length(home, "releasePhases")
        require(cacheWays == 2 && homeWays == 2 && cacheLines == 512 && homeLines == 512 &&
            acquireEntries == 2 && writebackEntries == 2, "actual cache/home owner geometry differs")
        report = Some(Map("schema" -> "store-prefetch-lru-victim-actual-component-v1",
            "mode" -> (if (enabled) "on" else "off"), "constructions" -> constructed,
            "cacheClass" -> cache.getClass.getName, "homeClass" -> home.getClass.getName,
            "cacheConcurrency" -> actual, "cacheGeometry" -> cacheGeometry, "homeGeometry" -> homeGeometry,
            "cacheLines" -> cacheLines, "cacheWays" -> cacheWays,
            "homeTrackedLines" -> homeLines, "homeTrackedWays" -> homeWays,
            "homeAcquireEntries" -> acquireEntries, "homeWritebackEntries" -> writebackEntries,
            "executingCpu" -> false, "qualificationInherited" -> false))
        top
    }, Array("--target-dir", args(0)))
    require(constructed == 1 && report.nonEmpty, "actual constructor audit did not run")
    Files.writeString(Paths.get(args(0), "actual-parameters.json"), json(report.get) + "\n")
}
