package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}

/** Same qualified Ethernet ON platform; only translatedResponseEmptyFlow changes. */
object EthernetEmptyFlow275GsimMain extends App {
    require(args.length == 2, "fresh-output-directory actual-native-json required")
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh output directory required")
    val reference = ujson.read(Files.readString(Paths.get(args(1))))
    require(reference("schema") == ujson.Str("combined-timing-repair-r1-native-actual-v1") &&
        reference("topPorts").arr.size == 76, "actual selected native reference required")
    val baseline = CombinedTimingRepairR1Profile.config(true)
    require(!baseline.translatedResponseEmptyFlow)
    val c = baseline.copy(translatedResponseEmptyFlow = true)
    require(c.copy(translatedResponseEmptyFlow = baseline.translatedResponseEmptyFlow) == baseline)
    val expected = ujson.read(reference.render())
    Seq("core", "profile").foreach { group =>
        require(reference(group)("translatedResponseEmptyFlow") == ujson.Bool(false))
        expected(group)("translatedResponseEmptyFlow") = ujson.Bool(true)
    }
    val network = c.network.copy(rxWritePrefetch = true, rxLineWrites = true)
    require(network.copy(rxWritePrefetch = c.network.rxWritePrefetch,
        rxLineWrites = c.network.rxLineWrites) == c.network)
    var built: Option[BoardSocGsim] = None
    val fir = ChiselStage.emitCHIRRTL {
        val dut = FpgaNextBoardGsim.build(c, verifyConfiguration = true, sharedTwoWordFetchPmp = true,
            disjointEvictionStoreOverlap = true, proofBankControlDecoupling = true,
            projectedRequestHead = true, factorPreparedStorePool = true, combinedTimingR1Audit = true,
            registerNextLineDecision = true, registeredMemoryPreparationDescriptor = true,
            backendNaturalAlignedPmp = true, ethernetRxOverride = Some(network))
        built = Some(dut)
        dut
    }
    val platform = built.get.observedPlatform
    val actual = CombinedTimingRepairR1Audit.json(
        CombinedTimingRepairR1Audit.capturePlatform(platform, c, true))
    Seq("core", "profile", "fieldOrder", "geometry", "clockHz", "featureFlags", "counts",
        "pmpDecisionObservation", "descriptorObservation").foreach { key =>
        require(actual(key) == expected(key), s"matched CPU/native actual mismatch: $key")
    }
    def field(instance: AnyRef, name: String): Any = {
        var cls: Class[_] = instance.getClass
        var found: Option[java.lang.reflect.Field] = None
        while (cls != null && found.isEmpty) {
            found = cls.getDeclaredFields.find(f => f.getName == name || f.getName.endsWith("$$" + name))
            cls = cls.getSuperclass
        }
        val f = found.getOrElse(throw new IllegalArgumentException("missing observed field: " + name))
        f.setAccessible(true)
        f.get(instance)
    }
    require(actual("core")("translatedResponseEmptyFlow") == ujson.Bool(true) &&
        actual("profile")("translatedResponseEmptyFlow") == ujson.Bool(true))
    val observedNetwork = field(platform, "networkDmaConfig").asInstanceOf[soc.ip.dma.NetworkDmaConfig]
    require(observedNetwork == network)
    val packet = platform.packetDma.get
    require(field(packet, "rxWritePrefetch") == true && field(packet, "rxLineWrites") == true)
    require(field(packet, "rxLineEntries") == c.dmaLineEntries && packet.io.rxLine.nonEmpty)
    require(c.dmaLineTransfers && c.dmaLineEntries == 4)
    val hardware = fir.replaceAll(" @\\[[^\\n]*?\\]", "")
    require(hardware.contains("module DmaLineArbiter"), "shared line arbiter must be instantiated")
    Files.createDirectories(out)
    Files.writeString(out.resolve("BoardSocGsim.fir"), fir)
    Files.writeString(out.resolve("BoardSocGsim.hardware.fir"), hardware)
    Files.writeString(out.resolve("actual-combined-timing-repair-gsim.json"), actual.render(indent = 2) + "\n")
    Files.writeString(out.resolve("actual-ethernet-rx.json"), ujson.Obj(
        "schema" -> "matched275-instantiated-ethernet-rx-v1",
        "network" -> CombinedTimingRepairR1Audit.json(observedNetwork),
        "packetRxWritePrefetch" -> field(packet, "rxWritePrefetch").asInstanceOf[Boolean],
        "packetRxLineWrites" -> field(packet, "rxLineWrites").asInstanceOf[Boolean],
        "packetRxLineEntries" -> field(packet, "rxLineEntries").asInstanceOf[Int],
        "rxLinePortPresent" -> packet.io.rxLine.nonEmpty,
        "globalLineEntries" -> c.dmaLineEntries,
        "physicalQualification" -> false).render(indent = 2) + "\n")
    CombinedTimingRepairR1FabricAudit.write(out.toString)
    println("PASS_MATCHED275_EMPTY_RESPONSE_FLOW_CHIRRTL_UNQUALIFIED")
}
