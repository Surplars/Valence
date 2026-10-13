package ooo

import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Elaboration-time inspection only: no hardware signals or state are added. */
object MatchingFabricAudit {
    private var actual: Option[Map[String, Any]] = None
    private def unique[T](instance: AnyRef, kind: Class[T]): T = {
        val fields = scala.collection.mutable.ArrayBuffer.empty[java.lang.reflect.Field]
        var declaring: Class[_] = instance.getClass
        while (declaring != null) {
            fields ++= declaring.getDeclaredFields.filter(f =>
                !java.lang.reflect.Modifier.isStatic(f.getModifiers) && f.getType == kind)
            declaring = declaring.getSuperclass
        }
        require(fields.size == 1, "actual constructor field absent/ambiguous: " + kind.getName)
        fields.head.setAccessible(true)
        kind.cast(fields.head.get(instance))
    }
    def capture(board: MatchingManagedBoard, expected: FpgaNextConfig): Unit = {
        val p = board.platform
        val cache = p.privateCache.get
        val actualCore = p.core.core.core.p
        val actualDdr = unique(p, classOf[DdrBridgeConfig])
        val actualCache = unique(cache, classOf[CoherentCacheConcurrency])
        require(actualCore == expected.coreParams && actualDdr == expected.ddr && actualCache == expected.cache)
        HeadDrainActualAudit.requireShape(expected)
        require(actualCore.taggedStoreReturns == expected.taggedStoreReturns)
        require(actualCore.cpuReturnConfig.map(c => (c.memoryEntries, c.storeBufferEntries, c.fpEnabled,
            c.handleBits, c.handleCount, c.tableEntries)) ==
            (if (expected.taggedStoreReturns) Some((4, 2, true, 3, 7, 8)) else None),
            "tagged board return namespace differs from exact 4/2/1 domain")
        require(p.core.core.core.backend.lsu.io.memory.request.bits.returnHandle.map(_.getWidth) ==
            (if (expected.taggedStoreReturns) Some(3) else None), "actual LSU optional port width changed")
        require(p.packetDma.get.txQueue.get.owned.size == expected.network.postedTxSlots)
        require(p.packetDma.get.slotOwned.size == expected.network.postedRxSlots)
        require(p.dmaArbiter.get.io.clients.size == 2 && p.debugDmaArbiter.get.io.clients.size == 2)
        actual = Some(Map(
            "schema" -> "matching-board-fabric-actual-v1",
            "publishedSourceBaseCommit" -> "9937714cee13e26e54b8aabc4d149585af22245b",
            "physicalComparisonCommit" -> "b1bb5d863f7ad5b034f148b18968d19e46ace75b",
            "qualificationInherited" -> false,
            "cpu" -> actualCore, "ddr" -> actualDdr, "cache" -> actualCache,
            "timingStages" -> TimingBatchActualAudit.capture(p, expected),
            "zeroCycleCleanup" -> ZeroCycleCleanupActualAudit.capture(p, expected),
            "ownerRow" -> OwnerRowActualAudit.capture(p, expected),
            "eagerPrefix" -> EagerPrefixActualAudit.capture(p, expected),
            "futureHome" -> FutureHomeActualAudit.capture(p, expected),
            "headDrain" -> HeadDrainActualAudit.capture(p, expected),
            "retirementIntent" -> RetirementIntentActualAudit.capture(p, expected),
            "placedTiming" -> PlacedTimingActualAudit.capture(p, expected),
            "actualLsuOwners" -> p.core.core.core.backend.lsu.slots.size,
            "actualRegisterPorts" -> p.platformRouter.get.io.registers.size,
            "actualPacketRxOwners" -> p.packetDma.get.slotOwned.size,
            "actualPacketTxOwners" -> p.packetDma.get.txQueue.get.owned.size,
            "packetDmaClass" -> p.packetDma.get.getClass.getName,
            "memoryDmaClass" -> p.dma.getClass.getName,
            "jtagLoaderClass" -> p.jtagLoader.get.getClass.getName,
            "innerDmaArbiterClass" -> p.dmaArbiter.get.getClass.getName,
            "outerDmaArbiterClass" -> p.debugDmaArbiter.get.getClass.getName,
            "innerDmaClients" -> p.dmaArbiter.get.io.clients.size,
            "outerDmaClients" -> p.debugDmaArbiter.get.io.clients.size,
            "dmaArbitration" -> "(memoryCopy,packet)->regular;(regular,jtag)->laneAdapter",
            "dmaDataSizeBits" -> p.shared.io.dma.request.bits.size.getWidth,
            "dmaDataMaskBits" -> p.shared.io.dma.request.bits.mask.getWidth,
            "memoryDmaLinePresent" -> p.dma.io.line.nonEmpty,
            "localUartAbsent" -> p.uart.isEmpty,
            "localUartCdcAbsent" -> p.uartCdc.isEmpty,
            "gmacCsrClass" -> board.gmac.csr.getClass.getName,
            "gmacFrontendClass" -> board.gmac.frontend.getClass.getName,
            "gmacAdapterClass" -> board.gmac.adapter.getClass.getName,
            "phyManagerClass" -> board.gmac.phy.getClass.getName,
            "mediaTransitionClass" -> board.gmac.media.getClass.getName,
            "mdioEngineClass" -> board.gmac.mdio.getClass.getName,
            "mdioArbiterClass" -> board.gmac.mdioOwner.getClass.getName,
            "uartAdmissionClass" -> board.uartAdmission.getClass.getName,
            "productionPhysicalClocksSimulated" -> false,
            "cdcQualified" -> false,
            "bscanPrimitiveSimulated" -> false,
            "nativeMediaEnginesSimulated" -> false,
            "replacementBoundaries" -> Seq(
                "VivadoBootRom -> same-latency programmable synchronous ROM",
                "UART CDC/native50MHz UART and CMU CDC/native50MHz CMU -> external one-credit register services",
                "GMAC media/CDC frame/config/rate/stop/counter/level interfaces -> explicit CPU-domain services",
                "recovered-clock watchdog -> CPU-visible service level",
                "RGMII/PHY pins -> frame service and Clause22 MDIO pad responder",
                "BSCAN/TCK transport/CDC -> synchronous DMI/link service",
                "asynchronous cold-reset assertion -> synchronous assertion with three CPU release stages",
                "MIG/UI250MHz/DDR device -> unchanged independent-RW R32/B32 AXI service")))
    }
    private def quote(s: String): String = "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
    private def json(v: Any): String = v match {
        case null => "null"
        case s: String => quote(s)
        case b: Boolean => b.toString
        case n: Int => n.toString
        case n: Long => n.toString
        case n: BigInt => n.toString
        case o: Option[_] => o.map(json).getOrElse("null")
        case m: collection.Map[_, _] => m.toSeq.sortBy(_._1.toString)
            .map { case (k, x) => quote(k.toString) + ":" + json(x) }.mkString("{", ",", "}")
        case s: Seq[_] => s.map(json).mkString("[", ",", "]")
        case p: Product => json(p.productElementNames.zip(p.productIterator).toMap)
        case _ => throw new IllegalArgumentException("unsupported audit value")
    }
    def write(directory: String): Unit = {
        require(actual.nonEmpty, "the actual matching envelope was not constructed")
        Files.writeString(Paths.get(directory, "actual-fabric.json"), json(actual.get) + "\n")
        PostedBoardConfiguration.writeCore(actual.get("cpu").asInstanceOf[OooParams], directory)
    }
}
