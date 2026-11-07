package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Structural checks only; behavioral evidence comes from the independent GSIM ledger. */
class ProtectedFpRetirementConfigSpec extends AnyFunSuite {
    private val p = ProtectedFpRetirementConfig.params
    private def registers(fir: String): Seq[String] =
        fir.linesIterator.map(_.trim).filter(line => line.startsWith("reg ") || line.startsWith("regreset ")).toSeq

    test("bounded fixture retains full tokens and all passive architectural FPR observations") {
        ChiselStage.emitCHIRRTL {
            val fixture = new ProtectedFpRetirementGsim
            val io = fixture.io
            assert(!io.elements.contains("headAuthorized") && !io.elements.contains("flush"))
            assert(!io.elements.contains("retire") && !io.elements.contains("acceptedStart"))
            for (token <- Seq(io.issue.bits.token, io.execute.bits.command.token, io.result.bits.token,
                io.complete.bits.token, io.commit0.bits, io.commit1.bits, io.ownerToken)) {
                assert(token.index.getWidth == 4 && token.tag.getWidth == 64)
            }
            assert(io.retireMatches.getWidth == 2 && io.statePhase.getWidth == 2)
            assert(io.result.bits.guestFault.isDefined && io.complete.bits.guestFault.isDefined)
            assert(io.elements.keys.count(_.startsWith("fpr_")) == 32)
            for (i <- 0 until 32) { assert(io.elements(s"fpr_$i").getWidth == 64) }
            assert(fixture.state.io.guestContext.isDefined && fixture.state.io.mutation.isDefined)
            assert(fixture.hypervisor.io.floatingPoint.isDefined)
            fixture
        }
    }

    test("composition uses real consumers and raw retirement without an active qualifier") {
        val fir = ChiselStage.emitCHIRRTL(new ProtectedFpRetirementGsim)
        val wrapper = fir.substring(fir.indexOf("module ProtectedFpRetirementGsim :"))
        val instances = wrapper.linesIterator.map(_.trim).filter(_.startsWith("inst ")).toSeq
        assert(instances.size == 3)
        for ((instance, module) <- Seq("state" -> "FloatingPointState", "owner" -> "ProtectedSystemOwner",
            "hypervisor" -> "HypervisorState")) {
            assert(instances.exists(_.startsWith(s"inst $instance of $module")))
        }
        // The acceptance bit is the wrapper's only register. The FPR/FS/fcsr/owner
        // state remains in production modules; observations never replace it.
        assert(registers(wrapper).size == 1 && registers(wrapper).head.contains("completionSeen"))
        for (connection <- Seq(
            "state.io.retire.valid, owner.io.retired",
            "state.io.retire.bits.index, owner.io.token.index",
            "state.io.retire.bits.tag, owner.io.token.tag",
            "owner.io.start.bits.token.index, state.io.issue.bits.token.index",
            "owner.io.start.bits.token.tag, state.io.issue.bits.token.tag",
            "owner.io.start.bits.instruction, state.io.issue.bits.instruction",
            "owner.io.complete.valid, completionAccepted",
            "owner.io.commits[0].valid, io.commit0.valid",
            "owner.io.commits[0].bits.index, io.commit0.bits.index",
            "owner.io.commits[0].bits.tag, io.commit0.bits.tag",
            "owner.io.commits[1].valid, io.commit1.valid",
            "owner.io.commits[1].bits.index, io.commit1.bits.index",
            "owner.io.commits[1].bits.tag, io.commit1.bits.tag",
            "hypervisor.io.floatingPoint.mutation.valid, state.io.mutation.valid",
            "hypervisor.io.floatingPoint.mutation.bits.guest, state.io.mutation.bits.guest")) {
            assert(wrapper.contains(connection), s"missing production connection: $connection")
        }
        assert(wrapper.contains("state.io.headAuthorized, UInt<1>(0h1)"))
        assert(wrapper.contains("state.io.flush, UInt<1>(0h0)"))
        assert(wrapper.contains("io.completeAccept") && wrapper.contains("state.io.complete.valid"))
        assert(wrapper.contains("state.io.issue.ready") && wrapper.contains("state.io.issue.valid"))
        assert(wrapper.contains("successful synthetic results only"))
        assert(wrapper.contains("status CSR and V setup must be idle"))
    }

    test("explicit component profile does not change actual core guards or defaults") {
        assert(p.robEntries == 16 && p.tagBits == 64 && p.commitWidth == 2)
        assert(p.hypervisorExperiment && p.machineSystem && p.virtualMemoryLevels == 3 && p.pmpEntries == 16)
        assert(p.fpConfig.resources == FloatingPointResourceConfig.fpga && p.fpConfig.complete)
        assert(!p.basicCounters && !p.atomicMemory && !OooParams().fpEnabled && !OooParams().hypervisorExperiment)
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
