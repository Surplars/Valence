package ooo

import soc.core.ooo.{FpgaNextConfig, FpgaNextSocTop}

object CombinedTimingRepairR1Profile {
    val identity = "combined-timing-repair-r1"
    def config(enabled: Boolean): FpgaNextConfig = CombinedTimingPmpR1Profile.config(false)
    def construct(enabled: Boolean): FpgaNextSocTop = new FpgaNextSocTop(
        config = config(enabled), debug = CombinedTimingPmpR1Profile.debug,
        bscanChain = CombinedTimingPmpR1Profile.bscanChain,
        preselectRedirectTokenMatches = false,
        sharedTwoWordFetchPmp = true, disjointEvictionStoreOverlap = true,
        projectedRequestHead = true, factorPreparedStorePool = true,
        proofBankControlDecoupling = true, registerNextLineDecision = enabled,
        registeredMemoryPreparationDescriptor = enabled, backendNaturalAlignedPmp = enabled)
}
