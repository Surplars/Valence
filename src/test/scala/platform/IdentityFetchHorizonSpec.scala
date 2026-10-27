package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform._

class IdentityFetchHorizonSpec extends AnyFunSuite {
    private val control = CommonA1RebuildProfile.FullR1M3CertifiedIngress
    private val candidate = CommonA1RebuildProfile.FullR1M3IdentityFetchHorizon
    private val ram = Seq(SideEffectFreeFetchRange(BigInt("80200000", 16), 128 * 1024))

    test("identity horizon is an exact single-flag descendant with unchanged capacities") {
        assert(!OooParams().fetchThirdPacketLookahead && !FpgaNextConfig.Selected.fetchThirdPacketLookahead)
        assert(!CommonCpuProfile.A1.fpga.fetchThirdPacketLookahead)
        assert(candidate.config == control.config.copy(fetchThirdPacketLookahead = true))
        assert(candidate.config.coreParams == control.config.coreParams.copy(fetchThirdPacketLookahead = true))
        assert(candidate.config.cache == control.config.cache && candidate.config.ddr == control.config.ddr)
        assert(candidate.name == "full-r1-m3-identity-fetch-horizon")
        assert(CommonA1RebuildProfile.named(candidate.name) == candidate)
        for (profile <- CommonA1RebuildProfile.all) {
            assert(profile.config.fetchThirdPacketLookahead == Set[CommonA1RebuildProfile](candidate,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4).contains(profile))
            assert(profile.config.coreParams.fetchThirdPacketLookahead == Set[CommonA1RebuildProfile](candidate,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3,
                CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4).contains(profile))
        }
        val p = candidate.config.coreParams
        assert(candidate.config.fetchTransactionSlots == 2 && p.renameWidth == 2 && p.commitWidth == 2)
        assert(p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 4 && p.storeBufferEntries == 2)
    }

    test("new strict policy rejects every old profile and no old policy accepts the new profile") {
        val policy = candidate.memoryProfile.get
        assert(policy == CommonA1MemoryProfile.ExperimentalIdentityFetchHorizon)
        policy.validate(candidate.config, CommonCpuTilePortParams())
        for (old <- CommonA1RebuildProfile.all.filterNot(_ == candidate)) {
            intercept[IllegalArgumentException] { policy.validate(old.config, CommonCpuTilePortParams()) }
            old.memoryProfile.foreach { p =>
                intercept[IllegalArgumentException] { p.validate(candidate.config, CommonCpuTilePortParams()) }
            }
        }
        intercept[IllegalArgumentException] { candidate.config.managedBoard() }
        intercept[IllegalArgumentException] { OooParams(fetchThirdPacketLookahead = true) }
        intercept[IllegalArgumentException] { FpgaNextConfig(fetchThirdPacketLookahead = true) }
        intercept[IllegalArgumentException] { candidate.config.copy(fetchTransactionSlots = 1) }
    }

    test("safe RAM interval metadata rejects malformed or wrapped bounds") {
        val limit = BigInt(1) << 64
        assert(SideEffectFreeFetchRange(limit - 8, 8).endExclusive == limit)
        for ((base, bytes) <- Seq((BigInt(-1), BigInt(8)), (BigInt(0), BigInt(0)),
            (BigInt(0), BigInt(-1)), (limit, BigInt(1)), (limit - 7, BigInt(8)))) {
            intercept[IllegalArgumentException] { SideEffectFreeFetchRange(base, bytes) }
        }
    }

    test("frontend rejects each unsupported topology rather than widening owner storage") {
        def emit(slots: Int = 2, compressed: Boolean = true, width: Int = 2,
            window: Boolean = true, aligned: Boolean = true, frontier: Boolean = false,
            prepared: Boolean = false, compact: Boolean = false, history: Boolean = false,
            ranges: Seq[SideEffectFreeFetchRange] = ram): String = ChiselStage.emitCHIRRTL(
                new SynchronousFetch(16, compressed, 16, width, alignedFetchPmp = aligned,
                    parallelFetchTagLookup = true, registeredWindow = window,
                    boundedRequestFrontier = frontier, fetchAddressBeforePmp = prepared,
                    compactCacheKeys = compact, fetchPreviousPacket = history,
                    transactionSlots = slots, fetchThirdPacketLookahead = true,
                    sideEffectFreeFetchRanges = ranges))
        val bad: Seq[() => String] = Seq(() => emit(slots = 1), () => emit(compressed = false),
            () => emit(width = 4), () => emit(window = false), () => emit(aligned = false),
            () => emit(frontier = true), () => emit(frontier = true, prepared = true),
            () => emit(compact = true), () => emit(history = true), () => emit(ranges = Seq.empty))
        for (f <- bad) intercept[IllegalArgumentException] { f() }
    }
}
