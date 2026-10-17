package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

/** Independent qualification only: no board preset enables this prototype. */
object PendingStoreProofFixture {
    def params(enabled: Boolean = true, slots: Int = 1): OooParams =
        BoardSocConfig.timingParams("staged-load-issue").copy(
            robEntries = 16, physicalRegs = 48, memoryEntries = 4, tagBits = 64,
            machineSystem = true, atomicMemory = true, pmpEntries = 16, virtualMemoryLevels = 3,
            virtualRamLoadPrecheck = true, canonicalVirtualStoreOverlap = true,
            bufferedRamStores = true, registeredMemoryRequests = true, registeredTranslationHeads = true,
            registeredTranslatedResponses = true, registeredFabricBoundary = true,
            registeredLoadReplay = true, loadOrderOlderRetire = true,
            parallelMemoryPreparation = true, parallelMemoryPayload = true, compactMemoryOperandSelect = true,
            precheckedDataRequestFlow = false, fastBufferedStoreRetire = false, fastHeadLoadRetire = false,
            speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 65536,
            memoryProofFrontier = false, frozenStoreProofTransport = true,
            pendingVirtualStoreProof = enabled, pendingVirtualStoreProofSlots = slots)
    def pmp(cfg: UInt, address: UInt): PmpState = {
        val state = WireDefault(0.U.asTypeOf(new PmpState))
        state.cfg(0) := cfg
        state.addr(0) := address
        PmpState.decodeRegions(state)
        state
    }
}
