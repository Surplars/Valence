package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Pure configuration/elaboration checks, not actual H+FP CPU qualification. */
class MemoryDomainSelectorConfigSpec extends AnyFunSuite {
    private val integer = OooParams(machineSystem = true, virtualMemoryLevels = 3, pmpEntries = 16)
    private val h = integer.copy(hypervisorExperiment = true)
    private val fp = integer.copy(floatingPoint = FloatingPointConfig.fullFD)
    private val guest = fp.copy(hypervisorExperiment = true)
    private val tagged = fp.copy(memoryEntries = 8, storeBufferEntries = 8, taggedStoreReturns = true,
        speculativeRamBase = BigInt("80000000", 16), speculativeRamBytes = 65536,
        bufferedRamStores = true, registeredMemoryRequests = true, registeredStoreResponseOwners = true)
    private val profiles = Seq(OooParams(), integer, h, fp, guest, tagged)
    private val nativeRequest = Set("atomic", "atomicOp", "address", "write", "size", "data", "mask",
        "virtualized", "precheckedLoad", "translationEpoch", "prefetchNextAllowed", "uncached")
    private val nativeResponse = Set("data", "error", "pageFault")
    private val selectorPorts = Set("integer", "memory", "hMemoryEpoch", "fpMemoryEpoch", "integerBusy",
        "hBusy", "fpMemoryBusy", "postedBusy", "prefetchBusy", "busy", "cpuBusy", "domain")
    private def registers(fir: String): Int =
        "(?m)^\\s*reg(?:reset)? ".r.findAllIn(fir).length

    test("preparation preserves defaults and unadvertised H and FP scope") {
        for (p <- Seq(OooParams(), BoardSocConfig.timingParams(BoardSocConfig.timingProfile),
            BoardSocConfig.boardParams(BoardSocConfig.timingProfile))) {
            assert(!p.hypervisorExperiment && !p.fpEnabled && !p.basicCounters)
            assert(!p.misaValue.testBit(7) && !p.misaValue.testBit(5) && !p.misaValue.testBit(3))
            assert(p.issueWidth == 2)
        }
        assert(!h.atomicMemory && !h.basicCounters)
        assert(guest.fpConfig == FloatingPointConfig.fullFD && guest.fpConfig.complete)
        assert(guest.fpConfig.resources == FloatingPointResourceConfig.baseline)
        assert(!guest.advertiseFloatingPoint && !guest.misaValue.testBit(7))
        assert(guest.misaValue == fp.misaValue && guest.advertisedIsa == fp.advertisedIsa)
    }

    test("selector preserves complete native payloads optional provenance and host-only handles without storage") {
        for (p <- profiles) {
            val extraPorts = (if (p.hypervisorExperiment)
                Set("h", "guestFault", "integerGuestFault", "hGuestFault") else Set.empty[String]) ++
                (if (p.fpEnabled) Set("fp") else Set.empty[String]) ++
                (if (p.hypervisorExperiment && p.fpEnabled) Set("fpGuestFault") else Set.empty[String])
            val handleField = if (p.cpuReturnConfig.isDefined) Set("returnHandle") else Set.empty[String]
            val fir = ChiselStage.emitCHIRRTL {
                val selector = new MemoryDomainSelector(p)
                assert(selector.io.elements.keySet == selectorPorts ++ extraPorts)
                for (port <- Seq(selector.io.integer, selector.io.memory)) {
                    assert(port.request.bits.elements.keySet == nativeRequest ++ handleField)
                    assert(port.response.bits.elements.keySet == nativeResponse ++ handleField)
                    port.request.bits.returnHandle.foreach(handle => assert(handle.getWidth == p.dataReturnHandleBits))
                    port.response.bits.returnHandle.foreach(handle => assert(handle.getWidth == p.dataReturnHandleBits))
                }
                for (port <- selector.io.h.toSeq ++ selector.io.fp.toSeq) {
                    assert(port.request.bits.elements.keySet == nativeRequest)
                    assert(port.response.bits.elements.keySet == nativeResponse)
                }
                for (metadata <- Seq(selector.io.guestFault, selector.io.integerGuestFault,
                    selector.io.hGuestFault, selector.io.fpGuestFault).flatten) {
                    assert(metadata.elements.keySet == Set("guestPageFault", "guestAddress",
                        "guestPhysicalAddress", "implicitPte"))
                    assert(metadata.guestPhysicalAddress.getWidth == 64)
                }
                selector
            }
            assert(registers(fir) == 0)
            assert(!fir.linesIterator.exists(_.trim.startsWith("inst ")))
        }
    }

    test("shared protected owner retains only existing state and the full retirement token") {
        for (p <- profiles) {
            val fir = ChiselStage.emitCHIRRTL {
                val owner = new ProtectedSystemOwner(p)
                assert(owner.io.elements.keySet == Set("start", "complete", "commits", "active", "token",
                    "contextMemoryEpoch", "hMemoryEpoch", "fpMemoryEpoch", "retireMatches", "retired"))
                assert(owner.io.start.bits.elements.keySet == Set("token", "instruction"))
                assert(owner.io.start.bits.instruction.getWidth == 32)
                assert(owner.io.token.index.getWidth == p.robBits && owner.io.token.tag.getWidth == p.tagBits)
                assert(owner.io.commits.length == p.commitWidth && owner.io.retireMatches.length == p.commitWidth)
                owner
            }
            assert(registers(fir) == 3 + (if (p.hypervisorExperiment) 1 else 0) + (if (p.fpEnabled) 1 else 0))
            assert(!fir.linesIterator.exists(_.trim.startsWith("inst ")))
        }
    }

    test("host FP handle is a separate reservation and does not enable tagged H") {
        val config = tagged.cpuReturnConfig.get
        assert(config.fpHandle == 16 && config.handleBits == 5 && config.handleCount == 17)
        val error = intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new MemoryDomainSelector(tagged.copy(hypervisorExperiment = true)))
        }
        assert(error.getMessage.contains("explicit-H memory retains the untagged native port"))
    }

    test("both actual-core H plus FP guards reject every prepared FP selector") {
        for (p <- Seq(guest, guest.copy(floatingPoint = FloatingPointConfig.fullF),
            h.copy(experimentalFloatingPoint = true))) {
            val systemError = intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new MachineSystemUnit(p, experimentalHypervisor = true))
            }
            assert(systemError.getMessage.contains("guest FP state is not yet integrated"))
            val backendError = intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new IntegerBackend(p, experimentalHypervisor = true))
            }
            assert(backendError.getMessage.contains(
                "experimental H uses owner-carried translated memory without host-only proofs"))
        }
    }
}
