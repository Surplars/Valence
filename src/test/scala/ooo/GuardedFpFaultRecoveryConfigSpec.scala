package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Configuration/structure checks only. Dynamic evidence requires independent GSIM replay. */
class GuardedFpFaultRecoveryConfigSpec extends AnyFunSuite {
    private val p = GuardedFpFaultRecoveryConfig.params
    private val hostPorts = Set("start", "complete", "retire", "trap", "csr", "setFs", "fs", "fcsr", "busy",
        "memory", "memoryBusy", "pmpState", "dataPrivilege", "virtualized", "guestAddress", "guestFault")

    test("memory profile retains optional architectural ports and default single FS bridge") {
        ChiselStage.emitCHIRRTL {
            val ordinary = new FloatingPointSystem(p)
            assert(ordinary.io.elements.keySet == hostPorts)
            assert(ordinary.io.guestContext.isEmpty && ordinary.io.mutation.isEmpty)
            assert(ordinary.fp.io.guestContext.isEmpty && ordinary.fp.io.mutation.isEmpty)
            assert(ordinary.memoryOption.isDefined)
            ordinary
        }
        ChiselStage.emitCHIRRTL {
            val system = new FloatingPointSystem(p, dualFs = true)
            assert(system.io.elements.keySet == hostPorts ++ Set("guestContext", "mutation"))
            assert(system.fp.io.guestContext.isDefined && system.fp.io.mutation.isDefined)
            assert(system.memoryOption.isDefined)
            system
        }
    }

    test("fixture composes genuine consumers without injected results or trap admission controller") {
        val fir = ChiselStage.emitCHIRRTL {
            val fixture = new GuardedFpFaultRecoveryGsim
            assert(!fixture.io.elements.contains("result") && !fixture.io.elements.contains("execute"))
            assert(!fixture.io.elements.contains("retire") && !fixture.io.elements.contains("flush"))
            assert(fixture.io.elements.keys.count(_.startsWith("fpr_")) == 32)
            for (token <- Seq(fixture.io.start.bits.token, fixture.io.complete.bits.token,
                fixture.io.commit0.bits, fixture.io.commit1.bits, fixture.io.ownerToken)) {
                assert(token.index.getWidth == 4 && token.tag.getWidth == 64)
            }
            fixture
        }
        val wrapper = fir.substring(fir.indexOf("module GuardedFpFaultRecoveryGsim :"))
        val instances = wrapper.linesIterator.map(_.trim).filter(_.startsWith("inst ")).toSeq
        assert(instances.size == 6)
        for ((instance, module) <- Seq("system" -> "FloatingPointSystem", "owner" -> "ProtectedSystemOwner",
            "hypervisor" -> "HypervisorState", "selector" -> "MemoryDomainSelector",
            "adapter" -> "GuestDataTranslationAdapter", "translator" -> "GuestTranslationService")) {
            assert(instances.exists(_.startsWith(s"inst $instance of $module")))
        }
        assert(!wrapper.linesIterator.map(_.trim).exists(x => x.startsWith("reg ") || x.startsWith("regreset ")))
        // Chisel may retain an aggregate connect or expand it into leaves. Both
        // spellings express the same binding; do not require one printer choice.
        def bound(connection: String): Boolean = {
            val pair = connection.split(", ")
            def exact(sink: String, source: String): Boolean =
                wrapper.linesIterator.map(_.trim).exists { line =>
                    val binding = s"connect $sink, $source"
                    line == binding || line.startsWith(binding + " ")
                }
            def search(sink: String, source: String): Boolean = {
                if (exact(sink, source)) true
                else if (sink.contains(".") && source.contains(".") &&
                    sink.substring(sink.lastIndexOf('.') + 1) == source.substring(source.lastIndexOf('.') + 1)) {
                    search(sink.substring(0, sink.lastIndexOf('.')), source.substring(0, source.lastIndexOf('.')))
                } else false
            }
            search(pair(0), pair(1))
        }
        for (connection <- Seq("system.io.retire.valid, owner.io.retired",
            "system.io.retire.bits.index, owner.io.token.index", "system.io.retire.bits.tag, owner.io.token.tag",
            "owner.io.complete.bits.data, system.io.complete.bits.data",
            "system.io.trap, io.trap.valid",
            "selector.io.fpMemoryEpoch, owner.io.fpMemoryEpoch",
            "system.io.guestContext.virtualized, hypervisor.io.virtualized",
            "hypervisor.io.floatingPoint.mutation.valid, system.io.mutation.valid")) {
            assert(bound(connection), s"missing production connection: $connection")
        }
        assert(fir.linesIterator.map(_.trim).exists(x => x.startsWith("inst ") &&
            x.contains(" of FloatingPointMemoryPipeline")))
        assert(fir.contains("FloatingPointMiscS") && fir.contains("FloatingPointMiscD"))
        assert(!fir.contains(" of FloatingPointSharedArithmetic") && !fir.contains(" of FloatingPointDivSqrt"))
    }

    test("moves plus memory subset stays unadvertised and both actual H FP guards reject it") {
        assert(p.issueWidth == 2 && p.commitWidth == 2 && p.robEntries == 16 && p.tagBits == 64)
        assert(p.fpConfig.f && p.fpConfig.d && p.fpConfig.signClassMove && p.fpConfig.memory)
        assert(!p.fpConfig.complete && !p.fpConfig.addSubtract && !p.fpConfig.compareMinMax)
        assert(!p.fpConfig.multiply && !p.fpConfig.divide && !p.fpConfig.squareRoot && !p.fpConfig.fusedMultiplyAdd)
        assert(!p.fpConfig.conversions && !p.advertiseFloatingPoint)
        assert(p.fpConfig.resources == FloatingPointResourceConfig.fpga)
        assert(!p.misaValue.testBit(5) && !p.misaValue.testBit(3))
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
