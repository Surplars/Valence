package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.HypervisorMachineCore
import soc.platform.{CommonCpuProfile, CommonMachinePlatform}

/** Constructor/configuration checks only; instruction and memory behavior belongs to GSIM. */
class GuestAtomicsConfigSpec extends AnyFunSuite {
    private val ramBase = BigInt("80000000", 16)
    private val ramBytes = BigInt(4096)

    test("default H core keeps A and H advertisement clear and has no atomic RAM window") {
        ChiselStage.emitCHIRRTL {
            val core = new HypervisorMachineCore()
            assert(!core.p.atomicMemory)
            assert(core.p.speculativeRamBase == 0 && core.p.speculativeRamBytes == 0)
            assert(!core.p.misaValue.testBit(0) && !core.p.misaValue.testBit(7))
            core
        }
    }

    test("explicit atomic RAM profile enables A while retaining clear misa H") {
        ChiselStage.emitCHIRRTL {
            val core = new HypervisorMachineCore(atomicMemory = true, ramBase = ramBase, ramBytes = ramBytes)
            assert(core.p.atomicMemory)
            assert(core.p.speculativeRamBase == ramBase && core.p.speculativeRamBytes == ramBytes)
            assert(core.p.misaValue.testBit(0) && !core.p.misaValue.testBit(7))
            core
        }
    }

    test("atomic constructors reject missing, invalid and partial-granule RAM windows") {
        // Each rejection occurs while building OooParams, before constructing the core datapath.
        val missing = intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new HypervisorMachineCore(atomicMemory = true))
        }
        assert(missing.getMessage.contains("atomics require an explicit RAM window"))
        for ((base, bytes, message) <- Seq(
            (BigInt(-64), ramBytes, "invalid speculative RAM range"),
            ((BigInt(1) << 64) - 64, BigInt(128), "invalid speculative RAM range"),
            (ramBase + 1, ramBytes, "whole reservation granules"),
            (ramBase, ramBytes - 1, "whole reservation granules")
        )) {
            val error = intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new HypervisorMachineCore(
                    atomicMemory = true, ramBase = base, ramBytes = bytes))
            }
            assert(error.getMessage.contains(message))
        }
    }

    test("platform rejects atomic selector without the experimental H tile") {
        // The selector guard is the first constructor requirement: no full platform elaboration.
        val error = intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new CommonMachinePlatform(
                profile = CommonCpuProfile.A1, experimentalHypervisorAtomics = true))
        }
        assert(error.getMessage.contains("guest atomics require the explicit experimental H tile"))
    }
}
