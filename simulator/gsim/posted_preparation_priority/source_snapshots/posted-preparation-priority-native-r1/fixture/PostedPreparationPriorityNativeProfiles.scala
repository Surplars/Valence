package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** One scheduling flag on the reviewed ROB64/PRF64/frontier/store-PF-LRU profile. */
object PostedPreparationPriorityNativeProfiles {
    def options(enabled: Boolean): Set[String] = StorePrefetchLruVictimProfiles.options(true) ++
        (if (enabled) Set("--posted-preparation-priority") else Set.empty[String])

    def profile(enabled: Boolean): FpgaNextConfig = {
        val baseline = StorePrefetchLruVictimProfiles.profile(true)
        val selected = FpgaNextConfig.fromOptions(options(enabled), defaultSelected = false)
        require(selected == baseline.copy(postedPreparationPriority = enabled))
        require(selected.productArity == 32 && selected.coreParams.productArity == 140)
        require(selected.coreParams == baseline.coreParams.copy(postedPreparationPriority = enabled))
        require(selected.cache == baseline.cache && selected.ddr == baseline.ddr &&
            selected.tags == baseline.tags && selected.storage == baseline.storage &&
            selected.network == baseline.network && selected.floatingPointResources == baseline.floatingPointResources)
        require(selected.memoryProofFrontier && selected.storePrefetchLruVictim)
        selected
    }

    def arguments(args: Array[String]): Boolean = {
        require(args.length == 2 && Set("off", "on").contains(args(1)),
            "fresh-output-directory and explicit off|on required")
        require(!Files.exists(Paths.get(args(0))), "posted preparation native audit requires a fresh directory")
        args(1) == "on"
    }
}

/** Constructor reports contain every current field, including the explicit OFF value. */
object PostedPreparationPriorityNativeProfileMain extends App {
    val enabled = PostedPreparationPriorityNativeProfiles.arguments(args)
    PostedBoardConfiguration.write(PostedPreparationPriorityNativeProfiles.profile(enabled), args(0))
}

/** Actual native construction audit; independent of component or CPU runtime qualification. */
object PostedPreparationPriorityNativeMain extends App {
    val enabled = PostedPreparationPriorityNativeProfiles.arguments(args)
    val profile = PostedPreparationPriorityNativeProfiles.profile(enabled)
    PostedBoardConfiguration.write(profile, args(0))
    new CanonicalVirtualStoreActualParamsAudit(profile, args(0), "on",
        PostedPreparationPriorityNativeProfiles.options(enabled), "posted-preparation-priority-" + args(1))
}

