package ooo

import java.nio.file.{Files, Paths}

/** Fresh native export of the exact original ROB64/PRF64 profile, with one frontier flag. */
object MemoryProofFrontierNativeMain extends App {
    require(args.length == 2 && Set("off", "on").contains(args(1)),
        "usage: MemoryProofFrontierNativeMain fresh-output-directory off|on")
    require(!Files.exists(Paths.get(args(0))), "native audit requires a fresh output directory")
    val enabled = args(1) == "on"
    val profile = MemoryProofFrontierExactFixture.profile(enabled)
    MemoryProofFrontierExactFixture.validate(profile.coreParams)
    val options = MemoryProofFrontierExactFixture.canonicalOptions ++
        (if (enabled) Set("--memory-proof-frontier") else Set.empty[String])
    PostedBoardConfiguration.write(profile, args(0))
    // The reused audit's mode names canonical-store overlap, which remains ON on both sides.
    // Frontier treatment is present in every fully inspected actual OooParams record.
    new CanonicalVirtualStoreActualParamsAudit(profile, args(0), "on", options,
        "memory-proof-frontier-native-" + args(1))
}
