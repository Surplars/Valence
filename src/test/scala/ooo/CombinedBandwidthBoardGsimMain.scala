package ooo

import _root_.circt.stage.ChiselStage
import chisel3.experimental.BaseModule
import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Exact current native CPU/fabric, with the existing documented simulation boundaries.
  * Production sources and the fixed native candidate remain unchanged.
  */
object CombinedBandwidthBoardGsimMain extends App {
    require(args.length == 2, "fresh model directory and actual fixed native audit required")
    val out = Paths.get(args(0)).toAbsolutePath
    val reference = ujson.read(Files.readString(Paths.get(args(1))))
    require(!Files.exists(out), "fresh model directory required")
    val c = ThreeProofRowNativeProfile.config
    def json(v: Any): ujson.Value = ujson.read(PostedBoardConfiguration.json(v))
    def children(m: BaseModule): Seq[BaseModule] =
        classOf[BaseModule].getMethod("getIds").invoke(m).asInstanceOf[scala.collection.Iterable[_]]
            .collect { case x: BaseModule => x }.toSeq
    def descendants(m: BaseModule): Seq[BaseModule] = m +: children(m).flatMap(descendants)
    def field(instance: AnyRef, name: String): Any = {
        var cls: Class[_] = instance.getClass
        var found: Option[java.lang.reflect.Field] = None
        while (cls != null && found.isEmpty) {
            found = cls.getDeclaredFields.find(f => f.getName == name || f.getName.endsWith("$$" + name))
            cls = cls.getSuperclass
        }
        val f = found.getOrElse(throw new IllegalArgumentException("actual field missing: " + name))
        f.setAccessible(true); f.get(instance)
    }
    require(json(c) == reference("profile") && json(c.coreParams) == reference("core"))
    require(json(Map("core" -> c.coreParams.productElementNames.toSeq,
        "profile" -> c.productElementNames.toSeq)) == reference("fieldOrder"))
    require(c.productArity == 95 && c.coreParams.productArity == 178)
    var actualTop: Option[BoardSocGsim] = None
    ChiselStage.emitCHIRRTLFile({
        val dut = FpgaNextBoardGsim.build(c, verifyConfiguration = true,
            sharedTwoWordFetchPmp = true, disjointEvictionStoreOverlap = true)
        actualTop = Some(dut)
        dut
    }, Array("--target-dir", out.toString))
        // Chisel permits getIds only after the top module has closed.
        val dut = actualTop.get
        val modules = descendants(dut).distinct
        val boards = modules.collect { case x: MatchingManagedBoard => x }
        require(boards.size == 1)
        val board = boards.head
        val platform = board.platform
        val backend = platform.core.core.core.backend
        val selectors = modules.collect { case x: ResidentMemoryPreparationSelector => x }
        val helpers = modules.collect { case x: SharedTwoWordFetchPmp => x }
        val adapters = modules.collect { case x: InstructionTranslationAdapter => x }
        val caches = modules.collect { case x: NonBlockingCoherentLineCache => x }
        require(selectors.size == 1 && selectors.head.rankResidentPriority && helpers.size == 2)
        require(adapters.size == 1 && adapters.head.sharedTwoWordFetchPmp)
        require(dut.sharedTwoWordFetchPmp && board.sharedTwoWordFetchPmp &&
            platform.sharedTwoWordFetchPmp && platform.frontend.sharedTwoWordFetchPmp)
        require(dut.disjointEvictionStoreOverlap && board.disjointEvictionStoreOverlap && platform.disjointEvictionStoreOverlap)
        require(caches.size == 1 && caches.head.disjointEvictionStoreOverlap && !caches.head.splitCacheableBounds)
        val cache = caches.head
        require(backend.p == c.coreParams && backend.ledger.p == c.coreParams)
        require(cache.shareStoreWriteData && cache.registerProbeLookup && cache.localReadSelection)
        val geometry = Map("cache" -> field(cache, "concurrency"), "ddr" -> field(platform, "ddrBridge"),
            "cacheLines" -> field(cache, "lines"), "cacheWays" -> field(cache, "ways"),
            "cacheBase" -> field(cache, "base"), "cacheBytes" -> field(cache, "bytes"),
            "proofRows" -> backend.pendingStoreProof.get.state.length,
            "earlyLoadCredits" -> backend.pendingStoreCredit.get.state.length,
            "lsuOwners" -> backend.lsu.slots.size)
        val features = Map("rankResidentPriority" -> selectors.head.rankResidentPriority,
            "sharedTwoWordFetchPmp" -> platform.frontend.sharedTwoWordFetchPmp,
            "disjointEvictionStoreOverlap" -> cache.disjointEvictionStoreOverlap,
            "splitCacheableBounds" -> cache.splitCacheableBounds)
        require(json(geometry) == reference("geometry") && json(features) == reference("featureFlags"))
        val result = Map("schema" -> "combined-bandwidth-gsim-actual-v1", "core" -> backend.p,
            "profile" -> c, "geometry" -> geometry, "featureFlags" -> features,
            "sharedPmpHelpers" -> helpers.size, "residentSelectors" -> selectors.size,
            "nativeCommonCpuFabricMatch" -> true, "qualificationInherited" -> false,
            "physicalClocksAndPhySimulated" -> false)
    MatchingFabricAudit.write(out.toString)
    Files.writeString(out.resolve("actual-combined-gsim.json"), json(result).render(indent = 2) + "\n")
    println("PASS_COMBINED_BANDWIDTH_GSIM_NATIVE_MATCH core=178 profile=95 helpers=2 lsu=4 proof_rows=3 runtime_pending")
}
