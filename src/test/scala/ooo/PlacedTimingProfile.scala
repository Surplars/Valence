package ooo

import soc.core.ooo._

/** Explicit candidate vectors only. No generic preset or frozen board release is changed. */
private[ooo] object PlacedTimingProfile {
    val defaultOptions = RetirementIntentCpuProfile.defaultOptions
    val timingOptions = Seq("--fetch-address-before-pmp", "--queued-head-selection", "--aligned-next-line-pmp",
        "--register-probe-lookup", "--local-address-ranges")
    val existingOptions = Seq("--predecoded-head-drain", "--retirement-intent")
    val componentOptions = defaultOptions ++ timingOptions
    val candidateOptions = defaultOptions ++ existingOptions ++ timingOptions
    val off = RetirementIntentCpuProfile.off
    val component = FpgaNextConfig.fromOptions(componentOptions.toSet, defaultSelected = false)
    val on = FpgaNextConfig.fromOptions(candidateOptions.toSet, defaultSelected = false)
    for (options <- Seq(defaultOptions, componentOptions, candidateOptions)) FpgaNextProfileOptions.validate(options)
    require(candidateOptions.take(52) == defaultOptions && candidateOptions.size == 59)
    def requireExact(c: FpgaNextConfig): Unit = {
        PlacedTimingProfileBridge.requireShape(c)
        require(c == off || c == component || c == on, "only explicit default52 OFF/component/combined profiles qualify")
        require(!c.futureHomeWayReservation && !c.cache.futureHomeWayReservation && !c.storePrefetchLruVictim &&
            !c.cache.storePrefetchLruVictim && !c.eagerFetchPrefixSelect && !c.coreParams.eagerFetchPrefixSelect)
        require(c.issueWidth == 2 && c.cpuHz == 100000000 && c.coreParams.robEntries == 16 &&
            c.coreParams.physicalRegs == 48 && c.coreParams.tagBits == 64)
    }
}
