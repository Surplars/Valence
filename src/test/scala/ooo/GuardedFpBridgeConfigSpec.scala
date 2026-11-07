package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Port/configuration proof only; arithmetic evidence is the independently checked GSIM trace. */
class GuardedFpBridgeConfigSpec extends AnyFunSuite {
    private val p = GuardedFpBridgeConfig.params
    private val hostPorts = Set("start", "complete", "retire", "trap", "csr", "setFs", "fs", "fcsr", "busy",
        "memory", "memoryBusy", "pmpState", "dataPrivilege", "virtualized", "guestAddress", "guestFault")
    private def registers(fir: String, name: String): Int =
        ("(?m)^\\s*reg(?:reset)? " + name + " : ").r.findAllIn(fir).length

    test("ordinary bridge retains its interface and single FS state even with H metadata") {
        val fir = ChiselStage.emitCHIRRTL {
            val system = new FloatingPointSystem(p)
            assert(system.io.elements.keySet == hostPorts)
            assert(system.io.guestContext.isEmpty && system.io.mutation.isEmpty)
            assert(system.fp.io.guestContext.isEmpty && system.fp.io.mutation.isEmpty)
            system
        }
        assert(!fir.contains("pendingGuest") && !fir.contains("guestContext"))
        assert(registers(fir, "fs") == 1 && registers(fir, "frm") == 1 && registers(fir, "flags") == 1)
        ChiselStage.emitCHIRRTL {
            val host = new FloatingPointSystem(p.copy(hypervisorExperiment = false))
            assert(host.io.elements.keySet == hostPorts -- Set("guestAddress", "guestFault"))
            host
        }
    }

    test("optional bridge forwards architecture separately from memory translation") {
        val fir = ChiselStage.emitCHIRRTL {
            val system = new FloatingPointSystem(p, dualFs = true)
            assert(system.io.elements.keySet == hostPorts ++ Set("guestContext", "mutation"))
            assert(system.fp.io.guestContext.isDefined && system.fp.io.mutation.isDefined)
            system
        }
        assert(registers(fir, "pendingGuest") == 1)
        assert(registers(fir, "fs") == 1 && registers(fir, "frm") == 1 && registers(fir, "flags") == 1)
        assert("cmem".r.findAllIn(fir).length == 1 && fir.contains("UInt<64>[32]"))
        assert(fir.contains("fp.io.guestContext.virtualized, io.guestContext.virtualized"))
        assert(fir.contains("fp.io.guestContext.fs, io.guestContext.fs"))
        assert(fir.contains("connect io.mutation, fp.io.mutation"))
        assert(fir.contains("inst execute of FloatingPointExecute"))
        assert(!fir.contains("inst memory of FloatingPointMemoryPipeline"))
    }

    test("fixture uses real execution and owner handshakes without producer injection") {
        val fir = ChiselStage.emitCHIRRTL {
            val fixture = new GuardedFpBridgeGsim
            assert(!fixture.io.elements.contains("result") && !fixture.io.elements.contains("execute"))
            assert(!fixture.io.elements.contains("retire") && !fixture.io.elements.contains("flush"))
            assert(fixture.io.elements.keys.count(_.startsWith("fpr_")) == 32)
            for (token <- Seq(fixture.io.start.bits.token, fixture.io.complete.bits.token,
                fixture.io.commit0.bits, fixture.io.commit1.bits, fixture.io.ownerToken)) {
                assert(token.index.getWidth == 4 && token.tag.getWidth == 64)
            }
            fixture
        }
        val wrapper = fir.substring(fir.indexOf("module GuardedFpBridgeGsim :"))
        val instances = wrapper.linesIterator.map(_.trim).filter(_.startsWith("inst ")).toSeq
        assert(instances.size == 3)
        for ((instance, module) <- Seq("system" -> "FloatingPointSystem", "owner" -> "ProtectedSystemOwner",
            "hypervisor" -> "HypervisorState")) {
            assert(instances.exists(_.startsWith(s"inst $instance of $module")))
        }
        assert(!wrapper.linesIterator.map(_.trim).exists(x => x.startsWith("reg ") || x.startsWith("regreset ")))
        for (connection <- Seq("system.io.retire.valid, owner.io.retired",
            "system.io.retire.bits.index, owner.io.token.index", "system.io.retire.bits.tag, owner.io.token.tag",
            "owner.io.complete.bits.data, system.io.complete.bits.data",
            "system.io.virtualized, io.translationActive",
            "system.io.guestContext.virtualized, hypervisor.io.virtualized",
            "hypervisor.io.floatingPoint.mutation.valid, system.io.mutation.valid")) {
            assert(wrapper.contains(connection), s"missing production connection: $connection")
        }
        assert(wrapper.contains("system.io.start.ready") && wrapper.contains("system.io.start.valid"))
        assert(wrapper.contains("system.io.complete.ready") && wrapper.contains("system.io.complete.valid"))
        assert(fir.contains("FloatingPointMiscS") && fir.contains("FloatingPointMiscD"))
        assert(fir.contains("FloatingPointShared"))
    }

    test("partial arithmetic profile remains unadvertised and both actual core guards reject it") {
        assert(p.issueWidth == 2 && p.commitWidth == 2 && p.robEntries == 16 && p.tagBits == 64)
        assert(!p.fpConfig.complete && p.fpConfig.addSubtract && p.fpConfig.signClassMove && p.fpConfig.compareMinMax)
        assert(!p.fpConfig.multiply && !p.fpConfig.divide && !p.fpConfig.squareRoot && !p.fpConfig.fusedMultiplyAdd)
        assert(!p.fpConfig.conversions && !p.fpConfig.memory && !p.advertiseFloatingPoint)
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
