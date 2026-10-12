package ooo

import soc.core.ooo._
import soc.bus.tilelink.TLParams

/** Read actual constructed objects. Adds no DUT ports, registers or observers. */
object ZeroCycleCleanupActualAudit {
    private def geometry(tl: TLParams, axiAddressWidth: Int, axiIdWidth: Int,
        maxBurstBeats: Int, axiAddressBase: BigInt, axiWindowBytes: BigInt,
        writeCollectionFlow: Boolean, lineReadChannel: Boolean,
        localPayloadWriteEnable: Boolean): Map[String, Any] = Map(
        "tlParams" -> tl, "sizeBits" -> tl.sizeBits, "sinkBits" -> tl.sinkBits,
        "sourceBits" -> tl.sourceBits, "addressBits" -> tl.addrWidth, "dataBits" -> tl.dataWidth,
        "axiAddressBits" -> axiAddressWidth, "axiIdBits" -> axiIdWidth,
        "maxBurstBeats" -> maxBurstBeats, "axiAddressBase" -> axiAddressBase,
        "axiWindowBytes" -> axiWindowBytes, "writeCollectionFlow" -> writeCollectionFlow,
        "lineReadChannel" -> lineReadChannel, "localPayloadWriteEnable" -> localPayloadWriteEnable)

    def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
        val backend = platform.core.core.core.backend
        val actualCore = platform.core.core.core.p
        require(actualCore == expected.coreParams && actualCore.productArity == 159)
        require(backend.p.directRegisteredExecutionOperands == expected.directRegisteredExecutionOperands &&
            backend.p.registeredIssueExecute, "actual registered execution operand option differs")
        val wrapper = platform.ddrManagerInstance.getOrElse(
            throw new IllegalArgumentException("actual external DDR manager was not constructed"))
        val manager = wrapper.outstandingInstance.getOrElse(
            throw new IllegalArgumentException("actual DDR slot manager was not constructed"))
        val wrapperGeometry = geometry(wrapper.tlParams, wrapper.axiAddressWidth, wrapper.axiIdWidth,
            wrapper.maxBurstBeats, wrapper.axiAddressBase, wrapper.axiWindowBytes,
            wrapper.writeCollectionFlow, wrapper.lineReadChannel, wrapper.localPayloadWriteEnable) ++ Map(
            "maxOutstanding" -> wrapper.maxOutstanding, "maxOutstandingWrites" -> wrapper.maxOutstandingWrites,
            "unorderedResponses" -> wrapper.unorderedResponses)
        val managerGeometry = geometry(manager.tlParams, manager.axiAddressWidth, manager.axiIdWidth,
            manager.maxBurstBeats, manager.axiAddressBase, manager.axiWindowBytes,
            manager.writeCollectionFlow, manager.lineReadChannel, manager.localPayloadWriteEnable) ++ Map(
            "maxOutstanding" -> manager.maxOutstanding, "maxOutstandingWrites" -> manager.maxOutstandingWrites,
            "unorderedResponses" -> manager.unorderedResponses)
        val required = geometry(soc.bus.tilelink.TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 5),
            32, 4, 16, BigInt("80200000", 16), BigInt(1) << 31, true, true,
            expected.localPayloadWriteEnable) ++ Map("maxOutstanding" -> 4,
            "maxOutstandingWrites" -> 2, "unorderedResponses" -> true)
        require(wrapperGeometry == required && managerGeometry == required,
            "actual DDR wrapper/manager constructor differs from exact four-slot geometry")
        require(wrapper.io.tl.a.bits.source.getWidth == 5 && manager.io.tl.a.bits.source.getWidth == 5 &&
            wrapper.io.tl.a.bits.size.getWidth == 3 && manager.io.tl.a.bits.size.getWidth == 3 &&
            wrapper.io.tl.d.bits.sink.getWidth == 1 && manager.io.tl.d.bits.sink.getWidth == 1 &&
            wrapper.io.axi.ar.bits.id.getWidth == 4 && manager.io.axi.ar.bits.id.getWidth == 4)
        require(manager.slots.size == 4, "actual DDR slot count differs")
        val slots = manager.slots.map { slot =>
            val actual = geometry(slot.tlParams, slot.axiAddressWidth, slot.axiIdWidth,
                slot.maxBurstBeats, slot.axiAddressBase, slot.axiWindowBytes,
                slot.writeCollectionFlow, slot.lineReadChannel, slot.localPayloadWriteEnable)
            require(actual == required -- Seq("maxOutstanding", "maxOutstandingWrites", "unorderedResponses"),
                "actual DDR slot constructor differs from its manager")
            require(slot.io.tl.a.bits.source.getWidth == 5 && slot.io.tl.a.bits.size.getWidth == 3 &&
                slot.io.tl.d.bits.sink.getWidth == 1 && slot.io.axi.ar.bits.id.getWidth == 4 &&
                slot.io.lineMode.nonEmpty && slot.io.lineData.get.getWidth == 512 && slot.payloadBanks.size == 8,
                "actual DDR slot ports or payload-bank count differ")
            actual + ("payloadBanks" -> slot.payloadBanks.size)
        }
        Map("schema" -> "actual-zero-cycle-cleanup-v1",
            "directRegisteredExecutionOperands" -> backend.p.directRegisteredExecutionOperands,
            "registeredIssueExecute" -> backend.p.registeredIssueExecute,
            "wrapper" -> wrapperGeometry, "manager" -> managerGeometry,
            "slotCount" -> manager.slots.size, "slots" -> slots)
    }
}
