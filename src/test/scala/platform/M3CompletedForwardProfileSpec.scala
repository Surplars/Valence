package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

class M3CompletedForwardProfileSpec extends AnyFunSuite {
    test("M3 changes only explicit completed canonical forwarding from full-r1") {
        val control = CommonA1RebuildProfile.FullR1.config
        val candidate = CommonA1RebuildProfile.FullR1M3.config
        assert(!CommonCpuProfile.A1.fpga.completedCanonicalStoreForwarding)
        assert(!CommonA1RebuildProfile.FullCandidate.config.completedCanonicalStoreForwarding)
        assert(!control.completedCanonicalStoreForwarding)
        assert(candidate == control.copy(completedCanonicalStoreForwarding = true))
        assert(candidate.coreParams == control.coreParams.copy(completedCanonicalStoreForwarding = true))
        assert(candidate.name != control.name)
        CommonA1RebuildProfile.FullR1M3.memoryProfile.get.validate(candidate, CommonCpuTilePortParams())
        intercept[IllegalArgumentException] { candidate.managedBoard() }
        val p = candidate.coreParams
        for (slots <- Seq(2, 4)) {
            val fir = ChiselStage.emitCHIRRTL(new ParallelLoadStoreUnit(p.copy(memoryEntries = slots), true))
            assert(fir.contains("canonicalForward"))
        }
    }
    test("M3 rejects incompatible ownership and unproved permission topologies") {
        val p = CommonA1RebuildProfile.FullR1M3.config.coreParams
        intercept[IllegalArgumentException] { p.copy(completionTopology = "legacy") }
        intercept[IllegalArgumentException] { p.copy(virtualRamLoadPrecheck = false) }
        intercept[IllegalArgumentException] { p.copy(canonicalVirtualStoreOverlap = false) }
        intercept[IllegalArgumentException] { p.copy(registeredCanonicalStoreEvent = true) }
        intercept[IllegalArgumentException] { p.copy(pendingVirtualStoreProof = true) }
        intercept[IllegalArgumentException] { p.copy(taggedStoreReturns = true) }
        intercept[IllegalArgumentException] { p.copy(postedStoreMerge = true) }
        intercept[IllegalArgumentException] { p.copy(memoryProofFrontier = true) }
    }
}
