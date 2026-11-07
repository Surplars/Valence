package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform.{CommonCpuProfile, CommonHypervisorCpuTile, CommonMachinePlatform}

/** Pure configuration/elaboration checks only. Counter and permission behavior belongs to GSIM. */
class GuestCountersConfigSpec extends AnyFunSuite {
    private def checkCore(core: HypervisorMachineCore, enabled: Boolean): Unit = {
        assert(core.p.basicCounters == enabled)
        assert(core.p.hypervisorExperiment && !core.p.atomicMemory)
        assert(!core.p.misaValue.testBit(0) && !core.p.misaValue.testBit(7))
        val backend = core.core.core.backend
        assert(backend.p.basicCounters == enabled)
        val system = backend.systemUnit.get
        assert(system.basicCounterBank.isDefined == enabled)
        assert(system.io.acceptedCommits.isDefined == enabled && system.io.counterRetire.isDefined == enabled)
    }

    test("basic counters and H remain disabled in existing default profiles") {
        for (p <- Seq(OooParams(), BoardSocConfig.boardParams(BoardSocConfig.timingProfile))) {
            assert(!p.basicCounters && !p.hypervisorExperiment)
            assert(!p.misaValue.testBit(7))
        }
    }

    test("explicit H counters preserve the baseline ISA and disabled A") {
        val h = OooParams(hypervisorExperiment = true, machineSystem = true,
            virtualMemoryLevels = 3, pmpEntries = 16)
        val counters = h.copy(basicCounters = true)
        assert(!h.basicCounters && counters.basicCounters)
        assert(counters.misaValue == h.misaValue && counters.advertisedIsa == h.advertisedIsa)
        assert(!counters.atomicMemory && !counters.misaValue.testBit(0) && !counters.misaValue.testBit(7))
    }

    test("basic counters require both the H experiment and machine system") {
        for (p <- Seq(OooParams(), OooParams(machineSystem = true), OooParams(hypervisorExperiment = true))) {
            val error = intercept[IllegalArgumentException] { p.copy(basicCounters = true) }
            assert(error.getMessage.contains("basic counters require the explicit experimental H machine-system profile"))
        }
    }

    test("default H core retains the counter-disabled parameter and port shape") {
        ChiselStage.emitCHIRRTL {
            val core = new HypervisorMachineCore()
            checkCore(core, enabled = false)
            core
        }
    }

    test("explicit H core counters propagate through the backend and system unit") {
        ChiselStage.emitCHIRRTL {
            val core = new HypervisorMachineCore(basicCounters = true)
            checkCore(core, enabled = true)
            core
        }
    }

    test("default H tile leaves its core counters disabled") {
        ChiselStage.emitCHIRRTL {
            val tile = new CommonHypervisorCpuTile(ramBytes = 4096, romBytes = 4096, mmioRegions = Seq.empty)
            checkCore(tile.core, enabled = false)
            tile
        }
    }

    test("explicit H tile counters reach the core without enabling A or advertising H") {
        ChiselStage.emitCHIRRTL {
            val tile = new CommonHypervisorCpuTile(ramBytes = 4096, romBytes = 4096,
                mmioRegions = Seq.empty, basicCounters = true)
            checkCore(tile.core, enabled = true)
            tile
        }
    }

    test("platform rejects the counter selector without the experimental H tile") {
        // The first constructor guard rejects this before full platform elaboration.
        val error = intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new CommonMachinePlatform(
                profile = CommonCpuProfile.A1, experimentalHypervisorCounters = true))
        }
        assert(error.getMessage.contains("basic counters require the explicit experimental H tile"))
    }
}
