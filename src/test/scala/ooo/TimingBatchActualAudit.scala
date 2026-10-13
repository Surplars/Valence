package ooo

import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Constructor observations from the exact emitted hierarchy. No DUT state is added. */
object TimingBatchActualAudit {
    def requireQueryStage(expected: Boolean, bank: Option[PendingVirtualStoreProof]): Boolean = {
        val actual = bank.exists(_.registerQuery)
        require(actual == expected, "actual pending query stage differs from its OooParams flag")
        actual
    }
    def requireFetchPorts(enabled: Boolean, ports: (String, Boolean)*): Unit = {
        require(ports.nonEmpty, "fetch phase audit requires actual optional ports")
        ports.foreach { case (name, present) =>
            require(present == enabled, s"fetch phase optional port mismatch: $name")
        }
    }
    def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
        PlacedTimingProfileBridge.requireShape(expected)
        val mapped = platform.core
        val machine = mapped.core
        val core = machine.core
        val backend = core.backend
        val adapter = mapped.observationTranslation.getOrElse(
            throw new IllegalArgumentException("actual staged data adapter is absent"))
        val actual = core.p
        require(actual == expected.coreParams && backend.p == actual,
            "emitted core/backend differs from the complete requested profile")
        require(backend.registerCanonicalStoreEvent == actual.registeredCanonicalStoreEvent &&
            adapter.registerCanonicalStoreEvent == actual.registeredCanonicalStoreEvent,
            "actual canonical event producer/backend configuration differs")
        val packet = core.fetchPacket.getOrElse(
            throw new IllegalArgumentException("actual registered fetch packet is absent"))
        require(packet.eagerPrefixSelect == actual.eagerFetchPrefixSelect,
            "actual selected packet eager prefix mode differs")
        require(packet.alignedPermissionStage == actual.alignedFetchPermissionStage &&
            platform.frontend.boundedRequestFrontier == actual.alignedFetchPermissionStage,
            "actual fetch packet/frontend mode differs")
        requireFetchPorts(actual.alignedFetchPermissionStage,
            "core offsets" -> core.io.instructionFaultOffsets.nonEmpty,
            "core frontier" -> core.io.fetchRequestFrontier.nonEmpty,
            "core suppress" -> core.io.suppressFetchRequest.nonEmpty,
            "machine offsets" -> machine.io.instructionFaultOffsets.nonEmpty,
            "machine frontier" -> machine.io.fetchRequestFrontier.nonEmpty,
            "machine suppress" -> machine.io.suppressFetchRequest.nonEmpty,
            "mapped offsets" -> mapped.io.instructionFaultOffsets.nonEmpty,
            "mapped frontier" -> mapped.io.fetchRequestFrontier.nonEmpty,
            "mapped suppress" -> mapped.io.suppressFetchRequest.nonEmpty,
            "packet phase input" -> packet.io.phaseInput.nonEmpty,
            "packet frontier" -> packet.io.requestFrontier.nonEmpty,
            "packet suppress" -> packet.io.suppressRequest.nonEmpty,
            "frontend frontier" -> platform.frontend.io.requestFrontier.nonEmpty,
            "frontend suppress" -> platform.frontend.io.suppressRequest.nonEmpty)
        require(backend.pendingStoreProof.nonEmpty == actual.pendingVirtualStoreProof)
        val queryRegistered = requireQueryStage(actual.registeredPendingStoreQuery, backend.pendingStoreProof)
        Map("schema" -> "timing-batch-actual-stage-parameters-v1",
            "registeredPendingStoreQuery" -> queryRegistered,
            "proofBankPresent" -> backend.pendingStoreProof.nonEmpty,
            "canonicalBackendRegistered" -> backend.registerCanonicalStoreEvent,
            "canonicalAdapterRegistered" -> adapter.registerCanonicalStoreEvent,
            "fetchPacketAlignedStage" -> packet.alignedPermissionStage,
            "fetchFrontendBoundedRequest" -> platform.frontend.boundedRequestFrontier,
            "coreFaultOffsetBits" -> core.io.instructionFaultOffsets.map(_(0).getWidth).getOrElse(0),
            "proofRows" -> actual.pendingVirtualStoreProofSlots,
            "earlyLoadCredits" -> actual.pendingStoreEarlyLoadCredits,
            "taggedStoreReturns" -> actual.taggedStoreReturns,
            "coreFields" -> actual.productArity,
            "profileFields" -> expected.productArity)
    }
    def write(actual: Map[String, Any], directory: String): Unit = {
        def atom(value: Any): String = value match {
            case text: String => "\"" + text.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
            case value: Boolean => value.toString
            case value: Int => value.toString
            case _ => throw new IllegalArgumentException("unsupported actual-stage value")
        }
        val json = actual.toSeq.sortBy(_._1).map { case (key, value) =>
            atom(key) + ":" + atom(value)
        }.mkString("{", ",", "}\n")
        Files.writeString(Paths.get(directory, "actual-stage-parameters.json"), json)
    }
}
