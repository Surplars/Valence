package ooo

import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Read-only native entry, using the same ordinary production constructor audit. */
object DistinctWayReleaseNativeMain extends App {
    require(args.length >= 3 && Set("off", "on").contains(args(1)))
    require(!Files.exists(Paths.get(args(0))), "fresh native output required")
    val options = args.drop(2).toSet
    require(options.size == args.length - 2)
    val on = args(1) == "on"
    val baseline = StorePrefetchLruVictimProfiles.profile(true).copy(postedPreparationPriority = true)
    val profile = FpgaNextConfig.fromOptions(options, defaultSelected = false)
    require(profile == baseline.copy(distinctWayRelease = on))
    require(profile.productArity == 33 && profile.coreParams.productArity == 140 && profile.cache.productArity == 12)
    require(profile.distinctWayRelease == on && profile.cache.distinctWayRelease == on)
    PostedBoardConfiguration.write(profile, args(0))
    new CanonicalVirtualStoreActualParamsAudit(profile, args(0), "on", options,
        "distinct-way-release-native-" + args(1))
}
