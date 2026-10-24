package platform

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo.FpgaNextConfig
import soc.platform._

class CommonA1MemoryProfileSpec extends AnyFunSuite {
    private val base = CommonCpuProfile.A1.fpga
    private val candidate = CommonA1MemoryProfile.experimentalMemoryParallel(base)
    private val profile = CommonA1MemoryProfile.ExperimentalMemoryParallel

    test("memory-parallel is an explicit candidate and preserves Selected and the shared platform") {
        assert(!base.virtualRamLoadPrecheck && base.lsuEntries == 2 && base.dataTranslationEntries == 8)
        assert(candidate.copy(lsuEntries = 2, dataTranslationEntries = 8,
            virtualRamLoadPrecheck = false, canonicalVirtualStoreOverlap = false,
            independentDemandAdmission = false, translationHitFlow = false,
            dataTlbWriteReadReuse = false, loadOrderOlderRetire = false) == base)
        assert(candidate.ddr == base.ddr && candidate.network == base.network && candidate.cpuHz == base.cpuHz)
        assert(candidate.instructionCacheLines == 512 && candidate.dataCacheLines == 512)
        assert(candidate.cache.readMshrs == 2 && candidate.cache.responseEntries == 2 &&
            candidate.cache.writebackEntries == 2)
        assert(FpgaNextConfig.Selected.lsuEntries == 2 && !FpgaNextConfig.Selected.virtualRamLoadPrecheck)
    }
    test("actual final core parameters retain four LSU owners and real ordered return boundaries") {
        profile.validate(candidate, CommonCpuTilePortParams())
        profile.validate(candidate, CommonCpuTilePortParams(runtimeMaintenance = true,
            runtimeCancellation = true, runtimeInterruptHold = true))
        val p = candidate.coreParams
        assert(p.memoryEntries == 4 && p.storeBufferEntries == 2 && p.robEntries == 16 && p.physicalRegs == 48)
        assert(p.registeredLoadIssueForwarding && p.virtualRamLoadPrecheck && p.canonicalVirtualStoreOverlap)
        assert(p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2)
        assert(p.dataReturnHandleBits == 0 && p.cpuReturnConfig.isEmpty && p.postedProofConfig.isEmpty)
    }
    test("typed profile rejects contradictory final configuration and hidden response protocols") {
        intercept[IllegalArgumentException] { profile.validate(base, CommonCpuTilePortParams()) }
        intercept[IllegalArgumentException] {
            profile.validate(candidate.copy(dataTranslationEntries = 8), CommonCpuTilePortParams())
        }
        intercept[IllegalArgumentException] {
            profile.validate(candidate.copy(translationHitFlow = false), CommonCpuTilePortParams())
        }
        intercept[IllegalArgumentException] {
            profile.validate(candidate.copy(taggedStoreReturns = true), CommonCpuTilePortParams())
        }
        intercept[IllegalArgumentException] {
            profile.validate(candidate.copy(translatedResponseEmptyFlow = true), CommonCpuTilePortParams())
        }
        intercept[IllegalArgumentException] { CommonA1MemoryProfile.experimentalMemoryParallel(candidate) }
    }
}
