package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Component preparation only. Actual H+FP integration must remain rejected. */
class DualFsPreparationConfigSpec extends AnyFunSuite {
    private val h = OooParams(hypervisorExperiment = true, machineSystem = true,
        virtualMemoryLevels = 3, pmpEntries = 16)
    private val forbidden = Seq(
        h.copy(floatingPoint = FloatingPointConfig.fullF),
        h.copy(floatingPoint = FloatingPointConfig.fullFD),
        h.copy(experimentalFloatingPoint = true))
    private val hostPorts = Set("headAuthorized", "flush", "issue", "execute", "result", "complete",
        "retire", "retireAccepted", "csr", "csrRead", "csrIllegal", "setFs", "fs", "sd", "fcsr", "busy")
    private def registers(fir: String, name: String): Int =
        ("(?m)^\\s*reg(?:reset)? " + name + " : ").r.findAllIn(fir).length

    test("preparation preserves default H FP A counters and ISA discovery") {
        val default = OooParams()
        assert(!default.hypervisorExperiment && !default.fpEnabled && !default.atomicMemory && !default.basicCounters)
        assert(!h.fpEnabled && !h.atomicMemory && !h.basicCounters)
        assert(!h.misaValue.testBit(7) && !h.misaValue.testBit(5) && !h.misaValue.testBit(3))
        assert(h.advertisedIsa == "rv64im_zicsr_zifencei")
        for (p <- Seq(default, BoardSocConfig.timingParams(BoardSocConfig.timingProfile),
            BoardSocConfig.boardParams(BoardSocConfig.timingProfile))) {
            assert(!p.hypervisorExperiment && !p.basicCounters && !p.fpEnabled)
            assert(!p.misaValue.testBit(7) && !p.misaValue.testBit(5) && !p.misaValue.testBit(3))
            assert(p.issueWidth == 2)
        }
        val hostFp = OooParams(machineSystem = true, floatingPoint = FloatingPointConfig.fullFD)
        assert(hostFp.fpConfig == FloatingPointConfig.fullFD && hostFp.fpConfig.complete)
        assert(hostFp.fpConfig.resources == FloatingPointResourceConfig.baseline)
        assert(!hostFp.advertiseFloatingPoint && !hostFp.misaValue.testBit(7))
    }

    test("actual MachineSystemUnit still rejects every full H plus FP selector") {
        for (p <- forbidden) {
            val error = intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new MachineSystemUnit(p, experimentalHypervisor = true))
            }
            assert(error.getMessage.contains("guest FP state is not yet integrated"))
        }
    }

    test("actual IntegerBackend independently retains its H plus FP guard") {
        for (p <- forbidden) {
            val error = intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new IntegerBackend(p, experimentalHypervisor = true))
            }
            assert(error.getMessage.contains(
                "experimental H uses owner-carried translated memory without host-only proofs"))
        }
    }

    test("ordinary host FP state retains its port shape and has no guest owner register") {
        for (resources <- Seq(FloatingPointResourceConfig.baseline, FloatingPointResourceConfig.fpga)) {
            val p = OooParams(machineSystem = true,
                floatingPoint = FloatingPointConfig.fullFD.copy(resources = resources))
            val fir = ChiselStage.emitCHIRRTL {
                val state = new FloatingPointState(p)
                assert(state.io.guestContext.isEmpty && state.io.mutation.isEmpty)
                assert(state.io.elements.keySet == hostPorts)
                state
            }
            assert(!fir.contains("pendingGuest") && !fir.contains("guestContext"))
            assert(registers(fir, "fs") == 1 && registers(fir, "frm") == 1 && registers(fir, "flags") == 1)
        }
    }

    test("dual FS adds one captured owner but retains one physical FPR and fcsr bank") {
        for (resources <- Seq(FloatingPointResourceConfig.baseline, FloatingPointResourceConfig.fpga)) {
            val p = OooParams(machineSystem = true,
                floatingPoint = FloatingPointConfig.fullFD.copy(resources = resources))
            val fir = ChiselStage.emitCHIRRTL {
                val state = new FloatingPointState(p, dualFs = true)
                assert(state.io.guestContext.isDefined && state.io.mutation.isDefined)
                assert(state.io.elements.keySet == hostPorts ++ Set("guestContext", "mutation"))
                state
            }
            assert(registers(fir, "pendingGuest") == 1)
            assert(registers(fir, "fs") == 1 && registers(fir, "frm") == 1 && registers(fir, "flags") == 1)
            if (resources.committedStateMemory) {
                assert("cmem".r.findAllIn(fir).length == 1 && fir.contains("UInt<64>[32]"))
                assert(!fir.contains("registerPayload"))
            } else {
                assert(registers(fir, "registerPayload") == 1 && fir.contains("UInt<64>[32]"))
                assert(!fir.contains("cmem"))
            }
        }
    }

    test("HypervisorState VS FS contract is absent by default and owns only VS metadata when enabled") {
        val ordinary = ChiselStage.emitCHIRRTL {
            val state = new HypervisorState(compressed = true, guestFiles = 0)
            assert(state.io.floatingPoint.isEmpty)
            state
        }
        assert(registers(ordinary, "vsfs") == 0 && !ordinary.contains("mutation"))
        val enabled = ChiselStage.emitCHIRRTL {
            val state = new HypervisorState(compressed = true, guestFiles = 0, floatingPoint = true)
            assert(state.io.floatingPoint.isDefined)
            state
        }
        assert(registers(enabled, "vsfs") == 1)
        assert(registers(enabled, "fs") == 0 && registers(enabled, "frm") == 0 && registers(enabled, "flags") == 0)
        assert(!enabled.contains("registerPayload") && !enabled.contains("cmem"))
    }
}
