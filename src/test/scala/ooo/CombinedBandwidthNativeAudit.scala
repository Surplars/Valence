package ooo

import chisel3._
import chisel3.experimental.{BaseModule, IntParam}
import chisel3.reflect.DataMirror
import soc.core.ooo._
import soc.ip.debug.{BscanRamTransport, JtagDebugReservation}
import soc.ip.ethernet.TriSpeedManagedGmac

/** Independent observations of the constructed experimental native hierarchy.
  * This does not load, modify, or inherit any frozen qualification manifest.
  */
object CombinedBandwidthNativeAudit {
    def json(x: Any): ujson.Value = ujson.read(PostedBoardConfiguration.json(x))
    private def children(m: BaseModule): Seq[BaseModule] =
        classOf[BaseModule].getMethod("getIds").invoke(m).asInstanceOf[scala.collection.Iterable[_]]
            .collect { case x: BaseModule => x }.toSeq
    private def descendants(m: BaseModule): Seq[BaseModule] = m +: children(m).flatMap(descendants)
    private def field(instance: AnyRef, name: String): Any = {
        var cls: Class[_] = instance.getClass
        var result: Option[java.lang.reflect.Field] = None
        while (cls != null && result.isEmpty) {
            result = cls.getDeclaredFields.find(f => f.getName == name || f.getName.endsWith("$$" + name))
            cls = cls.getSuperclass
        }
        val f = result.getOrElse(throw new IllegalArgumentException("actual field missing: " + name))
        f.setAccessible(true)
        f.get(instance)
    }
    private def leaves(name: String, data: Data): Seq[Map[String, Any]] = data match {
        case record: Record => record.elements.toSeq.flatMap { case (n, d) => leaves(name + "_" + n, d) }
        case vector: Vec[_] => vector.zipWithIndex.flatMap { case (d, i) => leaves(name + "_" + i, d) }.toSeq
        case _ => Seq(Map("name" -> name, "width" -> data.getWidth,
            "direction" -> DataMirror.directionOf(data).toString))
    }
    def capture(dut: FpgaNextSocTop, c: FpgaNextConfig, enabled: Boolean): Map[String, Any] = {
        val modules = descendants(dut).distinct
        val p = dut.board.platform
        val backend = p.core.core.core.backend
        val selectors = modules.collect { case m: ResidentMemoryPreparationSelector => m }
        val helpers = modules.collect { case m: SharedTwoWordFetchPmp => m }
        val adapters = modules.collect { case m: InstructionTranslationAdapter => m }
        val caches = modules.collect { case m: NonBlockingCoherentLineCache => m }
        val macs = modules.collect { case m: TriSpeedManagedGmac => m }
        val scans = modules.collect { case m: BscanRamTransport => m }
        val taps = modules.count(_.isInstanceOf[JtagDebugReservation])
        require(c.productArity == 95 && c.coreParams.productArity == 178)
        require(p.core.core.core.p == c.coreParams && backend.p == c.coreParams && backend.ledger.p == c.coreParams)
        require(selectors.size == 1 && selectors.head.rankResidentPriority)
        require(helpers.size == (if (enabled) 2 else 0))
        require(adapters.size == 1 && adapters.head.sharedTwoWordFetchPmp == enabled)
        require(dut.sharedTwoWordFetchPmp == enabled && dut.board.sharedTwoWordFetchPmp == enabled &&
            p.sharedTwoWordFetchPmp == enabled && p.frontend.sharedTwoWordFetchPmp == enabled)
        require(dut.disjointEvictionStoreOverlap == enabled && dut.board.disjointEvictionStoreOverlap == enabled &&
            p.disjointEvictionStoreOverlap == enabled)
        require(caches.size == 1 && caches.head.disjointEvictionStoreOverlap == enabled && !caches.head.splitCacheableBounds)
        val cache = caches.head
        require(field(cache, "concurrency") == c.cache && field(p, "ddrBridge") == c.ddr)
        require(field(cache, "lines") == 512 && field(cache, "ways") == 2)
        require(cache.shareStoreWriteData && cache.registerProbeLookup && cache.localReadSelection)
        require(backend.pendingStoreProof.get.state.length == 3 && backend.pendingStoreCredit.get.state.length == 2)
        require(backend.lsu.slots.size == 4 && backend.p.robEntries == 16 && backend.p.physicalRegs == 48)
        require(macs.size == 1 && macs.head.rawClockHandoff && macs.head.rawHandoff.nonEmpty &&
            dut.board.triSpeedRawClockHandoff && dut.board.nativeBank.get.triSpeedRawClockHandoff)
        require(scans.size == 1 && scans.head.params ==
            Map("ENABLE" -> IntParam(BigInt(1)), "JTAG_CHAIN" -> IntParam(BigInt(2))))
        require(taps == 0 && p.jtagLoader.nonEmpty && dut.board.jtagDmi.nonEmpty)
        require(c.cpuHz == 100000000 && c.aonHz == 50000000 && c.uartHz == 50000000 && c.ddrUiHz == 250000000)
        val ports = DataMirror.modulePorts(dut).toSeq.flatMap { case (name, data) => leaves(name, data) }
        require(ports.size == 76, s"native top boundary changed: ${ports.size} ports")
        Map("schema" -> "combined-bandwidth-native-actual-v1",
            "configurationBasis" -> "ThreeProofRowNativeProfile explicit constructor; independent experimental evidence",
            "qualificationInherited" -> false, "physicalQualification" -> false,
            "featureFlags" -> Map("rankResidentPriority" -> selectors.head.rankResidentPriority,
                "sharedTwoWordFetchPmp" -> p.frontend.sharedTwoWordFetchPmp,
                "disjointEvictionStoreOverlap" -> cache.disjointEvictionStoreOverlap,
                "splitCacheableBounds" -> cache.splitCacheableBounds),
            "counts" -> Map("residentSelectors" -> selectors.size, "sharedPmpHelpers" -> helpers.size,
                "nonBlockingCaches" -> caches.size, "nativeMacs" -> macs.size,
                "bscanTransports" -> scans.size, "standaloneTaps" -> taps),
            "coreFields" -> c.coreParams.productArity, "profileFields" -> c.productArity,
            "core" -> backend.p, "profile" -> c,
            "fieldOrder" -> Map("core" -> c.coreParams.productElementNames.toSeq,
                "profile" -> c.productElementNames.toSeq),
            "geometry" -> Map("cache" -> field(cache, "concurrency"), "ddr" -> field(p, "ddrBridge"),
                "cacheLines" -> field(cache, "lines"), "cacheWays" -> field(cache, "ways"),
                "cacheBase" -> field(cache, "base"), "cacheBytes" -> field(cache, "bytes"),
                "proofRows" -> backend.pendingStoreProof.get.state.length,
                "earlyLoadCredits" -> backend.pendingStoreCredit.get.state.length, "lsuOwners" -> backend.lsu.slots.size),
            "nativeBoundaries" -> Map("rawHandoffPresent" -> macs.head.rawHandoff.nonEmpty,
                "bscanChain" -> scans.head.params("JTAG_CHAIN").asInstanceOf[IntParam].value,
                "ramLoaderPresent" -> p.jtagLoader.nonEmpty, "nativeMacPhysicalGenericsApplied" -> false),
            "clockHz" -> Map("cpu" -> c.cpuHz, "aon" -> c.aonHz, "uart" -> c.uartHz, "ddrUi" -> c.ddrUiHz),
            "topPorts" -> ports)
    }
}
