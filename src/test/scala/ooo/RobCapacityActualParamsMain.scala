package ooo

import java.nio.file.{Files, Paths}
import soc.core.ooo.FpgaNextConfig

/** Capacity experiments retain the complete current recommended profile.
  * `default` is the exact no-capacity-option compatibility bridge.
  */
object RobCapacityProfiles {
    val names = Set("default", "rob16-prf48", "rob16-prf64", "rob32-prf64", "rob64-prf64")
    def options(name: String): Set[String] = {
        require(names.contains(name), "unknown ROB capacity profile")
        val capacity = if (name == "default") Set.empty[String] else {
            val parts = name.split("-")
            Set("--rob-entries=" + parts(0).stripPrefix("rob"),
                "--physical-regs=" + parts(1).stripPrefix("prf"))
        }
        PostedPrefetchBoardProfiles.options("head-offer", "on") ++
            Set("--canonical-virtual-store-overlap") ++ capacity
    }
    def profile(name: String): FpgaNextConfig = FpgaNextConfig.fromOptions(options(name), defaultSelected = true)
}

/** Actual final module parameters and CHIRRTL, with no simulator or native synthesis.
  * Both modes inspect six core, three cache, two DDR and actual cache TL parameter records.
  */
object RobCapacityActualParamsMain extends App {
    require(args.length == 3 && Set("board", "native").contains(args(1)),
        "usage: RobCapacityActualParamsMain fresh-output-directory board|native capacity-profile")
    require(!Files.exists(Paths.get(args(0))), "capacity audit requires a fresh directory")
    val profile = RobCapacityProfiles.profile(args(2))
    val options = RobCapacityProfiles.options(args(2))
    PostedBoardConfiguration.write(profile, args(0))
    if (args(1) == "board")
        new PostedBoardActualParamsAudit(profile, args(0), "on", options, "rob-capacity-" + args(2))
    else
        new CanonicalVirtualStoreActualParamsAudit(profile, args(0), "on", options, "rob-capacity-" + args(2))
}
