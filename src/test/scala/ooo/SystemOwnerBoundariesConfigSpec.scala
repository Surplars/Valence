package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Narrow fixture checks; broader selector shapes remain in the prior suite. */
class SystemOwnerBoundariesConfigSpec extends AnyFunSuite {
    private val p = SystemOwnerBoundariesConfig.params
    private def registers(fir: String): Int = "(?m)^\\s*reg(?:reset)? ".r.findAllIn(fir).length

    test("boundary ABI carries accepted exceptions and both full retirement tokens") {
        ChiselStage.emitCHIRRTL {
            val fixture = new SystemOwnerBoundariesGsim
            val io = fixture.io
            assert(io.elements.keySet == Set("acceptedStart", "acceptedComplete", "commit0", "commit1",
                "integer", "h", "fp", "memory", "integerBusy", "hBusy", "fpMemoryBusy", "postedBusy",
                "prefetchBusy", "busy", "cpuBusy", "ownerActive", "ownerToken", "contextMemoryEpoch",
                "hMemoryEpoch", "fpMemoryEpoch", "domain", "retired", "retireMatches"))
            assert(io.acceptedComplete.bits.elements.keySet == Set("token", "exception"))
            assert(io.acceptedComplete.bits.exception.getWidth == 1)
            for (token <- Seq(io.acceptedStart.bits.token, io.acceptedComplete.bits.token,
                io.commit0.bits, io.commit1.bits, io.ownerToken)) {
                assert(token.index.getWidth == 4 && token.tag.getWidth == 64)
            }
            assert(io.retireMatches.getWidth == 2 && io.domain.getWidth == 2)
            for (port <- Seq(io.integer, io.h, io.fp, io.memory)) {
                assert(port.request.bits.returnHandle.isEmpty && port.response.bits.returnHandle.isEmpty)
                assert(port.request.bits.address.getWidth == 64 && port.response.bits.data.getWidth == 64)
            }
            fixture
        }
    }

    test("fixture contains exactly the real owner and stateless selector with no replacement state") {
        val fir = ChiselStage.emitCHIRRTL(new SystemOwnerBoundariesGsim)
        val instances = fir.linesIterator.map(_.trim).filter(_.startsWith("inst ")).toSeq
        assert(instances.size == 2)
        assert(instances.exists(_.startsWith("inst owner of ProtectedSystemOwner")))
        assert(instances.exists(_.startsWith("inst selector of MemoryDomainSelector")))
        assert(registers(fir) == 5)
        val wrapper = fir.substring(fir.indexOf("module SystemOwnerBoundariesGsim :"))
        assert(registers(wrapper) == 0)
        assert(!wrapper.contains("mux(") && !wrapper.contains("regreset "))
        assert(wrapper.contains("owner.io.complete.bits.exception, io.acceptedComplete.bits.exception"))
        assert(wrapper.contains("selector.io.hMemoryEpoch, owner.io.hMemoryEpoch"))
        assert(wrapper.contains("selector.io.fpMemoryEpoch, owner.io.fpMemoryEpoch"))
    }

    test("test-only explicit parameters preserve production defaults and both actual H plus FP guards") {
        assert(p.robEntries == 16 && p.tagBits == 64 && p.commitWidth == 2 && p.issueWidth == 2)
        assert(p.virtualMemoryLevels == 3 && p.pmpEntries == 16)
        assert(p.cpuReturnConfig.isEmpty && !p.bufferedRamStores && !p.basicCounters)
        for (defaults <- Seq(OooParams(), BoardSocConfig.timingParams(BoardSocConfig.timingProfile),
            BoardSocConfig.boardParams(BoardSocConfig.timingProfile))) {
            assert(!defaults.hypervisorExperiment && !defaults.fpEnabled && !defaults.basicCounters)
            assert(defaults.issueWidth == 2)
            assert(!defaults.misaValue.testBit(7) && !defaults.misaValue.testBit(5) &&
                !defaults.misaValue.testBit(3))
        }
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
