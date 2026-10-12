package ooo

import java.nio.file.{Files, Paths}
import soc.bus.tilelink.TLParams
import soc.core.ooo._

/** Read actual constructed objects without adding DUT ports, registers or observers. */
object OwnerRowActualAudit {
    private def flags(row: Boolean, localEnable: Boolean, lineRead: Boolean): Map[String, Any] = {
        require(!row || (localEnable && lineRead), "actual local payload row lacks its prerequisites")
        Map("localPayloadWriteRow" -> row, "localPayloadWriteEnable" -> localEnable,
            "lineReadChannel" -> lineRead)
    }

    private def geometry(tl: TLParams, addressWidth: Int, idWidth: Int, beats: Int,
        base: BigInt, window: BigInt, collection: Boolean): Map[String, Any] =
        Map("tl" -> tl, "addressWidth" -> addressWidth, "idWidth" -> idWidth,
            "beats" -> beats, "base" -> base, "window" -> window, "collection" -> collection)

    def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
        val core = platform.core.core.core
        val backend = core.backend
        require(core.p == expected.coreParams && backend.p == core.p && core.p.productArity == 159,
            "actual owner-row core differs from the complete requested profile")
        require(expected.productArity == 71 && expected.ddr.productArity == 9 && expected.cache.productArity == 22)
        require(backend.shareCanonicalStoreOwnerMatch == backend.p.sharedCanonicalStoreOwnerMatch &&
            backend.shareCanonicalStoreOwnerMatch == expected.sharedCanonicalStoreOwnerMatch,
            "actual shared canonical-store owner comparator differs from its OooParams flag")
        require(!backend.shareCanonicalStoreOwnerMatch || backend.p.canonicalVirtualStoreOverlap,
            "actual shared canonical-store owner comparator lacks canonical overlap")

        val wrapper = platform.ddrManagerInstance.getOrElse(
            throw new IllegalArgumentException("actual external DDR manager was not constructed"))
        val manager = wrapper.outstandingInstance.getOrElse(
            throw new IllegalArgumentException("actual DDR slot manager was not constructed"))
        require(Set(8, 16).contains(wrapper.maxBurstBeats) && wrapper.maxBurstBeats == expected.ddr.maxBurstBeats,
            "actual SoC DDR burst must match the requested 8 or 16 beat geometry")
        val requiredGeometry = geometry(TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 5),
            32, 4, wrapper.maxBurstBeats, BigInt("80200000", 16), BigInt(1) << 31,
            expected.ddr.writeCollectionFlow)
        require(geometry(wrapper.tlParams, wrapper.axiAddressWidth, wrapper.axiIdWidth,
            wrapper.maxBurstBeats, wrapper.axiAddressBase, wrapper.axiWindowBytes,
            wrapper.writeCollectionFlow) == requiredGeometry &&
            geometry(manager.tlParams, manager.axiAddressWidth, manager.axiIdWidth,
                manager.maxBurstBeats, manager.axiAddressBase, manager.axiWindowBytes,
                manager.writeCollectionFlow) == requiredGeometry,
            "actual DDR wrapper/manager geometry differs")
        require(wrapper.maxOutstanding == expected.ddr.maxOutstanding &&
            manager.maxOutstanding == expected.ddr.maxOutstanding &&
            wrapper.maxOutstandingWrites == expected.ddr.maxOutstandingWrites &&
            manager.maxOutstandingWrites == expected.ddr.maxOutstandingWrites &&
            wrapper.unorderedResponses == expected.ddr.unorderedResponses &&
            manager.unorderedResponses == expected.ddr.unorderedResponses &&
            manager.slots.size == expected.ddr.maxOutstanding,
            "actual owner-row DDR scheduler differs from the requested profile")
        val requiredFlags = flags(expected.localPayloadWriteRow, expected.localPayloadWriteEnable,
            expected.lineReadChannel)
        require(requiredFlags == flags(expected.ddr.localPayloadWriteRow,
            expected.ddr.localPayloadWriteEnable, expected.ddr.lineReadChannel),
            "profile and DDR owner-row flags differ")
        val wrapperFlags = flags(wrapper.localPayloadWriteRow, wrapper.localPayloadWriteEnable,
            wrapper.lineReadChannel)
        val managerFlags = flags(manager.localPayloadWriteRow, manager.localPayloadWriteEnable,
            manager.lineReadChannel)
        require(wrapperFlags == requiredFlags && managerFlags == requiredFlags,
            "actual DDR wrapper/manager owner-row flags differ")
        require(wrapper.io.tl.a.bits.source.getWidth == 5 && manager.io.tl.a.bits.source.getWidth == 5 &&
            wrapper.io.tl.a.bits.size.getWidth == 3 && manager.io.tl.a.bits.size.getWidth == 3 &&
            wrapper.io.tl.d.bits.sink.getWidth == 1 && manager.io.tl.d.bits.sink.getWidth == 1 &&
            wrapper.io.axi.ar.bits.id.getWidth == 4 && manager.io.axi.ar.bits.id.getWidth == 4 &&
            wrapper.io.lineRead.nonEmpty == expected.lineReadChannel &&
            manager.io.lineRead.nonEmpty == expected.lineReadChannel,
            "actual DDR wrapper/manager ports differ")
        val slots = manager.slots.map { slot =>
            require(geometry(slot.tlParams, slot.axiAddressWidth, slot.axiIdWidth,
                slot.maxBurstBeats, slot.axiAddressBase, slot.axiWindowBytes,
                slot.writeCollectionFlow) == requiredGeometry, "actual DDR slot geometry differs")
            val actual = flags(slot.localPayloadWriteRow, slot.localPayloadWriteEnable, slot.lineReadChannel)
            require(actual == requiredFlags, "actual DDR physical slot owner-row flags differ")
            require(slot.io.tl.a.bits.source.getWidth == 5 && slot.io.tl.a.bits.size.getWidth == 3 &&
                slot.io.tl.d.bits.sink.getWidth == 1 && slot.io.axi.ar.bits.id.getWidth == 4 &&
                slot.io.lineMode.nonEmpty == expected.lineReadChannel &&
                slot.io.lineData.map(_.getWidth) == (if (expected.lineReadChannel) Some(512) else None) &&
                slot.payloadBanks.size == (if (expected.lineReadChannel) 8 else 0),
                "actual DDR slot ports or payload-bank count differ")
            actual
        }
        Map("schema" -> "actual-owner-row-v1",
            "sharedCanonicalStoreOwnerMatch" -> backend.shareCanonicalStoreOwnerMatch,
            "canonicalVirtualStoreOverlap" -> backend.p.canonicalVirtualStoreOverlap,
            "wrapper" -> wrapperFlags, "manager" -> managerFlags,
            "slotCount" -> manager.slots.size, "slots" -> slots)
    }

    def write(actual: Map[String, Any], directory: String): Unit = {
        def json(value: Any): String = value match {
            case text: String => "\"" + text.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
            case value: Boolean => value.toString
            case value: Int => value.toString
            case fields: collection.Map[_, _] => fields.toSeq.sortBy(_._1.toString)
                .map { case (key, item) => json(key.toString) + ":" + json(item) }.mkString("{", ",", "}")
            case items: Seq[_] => items.map(json).mkString("[", ",", "]")
            case _ => throw new IllegalArgumentException("unsupported actual owner-row value")
        }
        Files.createDirectories(Paths.get(directory))
        Files.writeString(Paths.get(directory, "actual-owner-row.json"), json(actual) + "\n")
    }
}
