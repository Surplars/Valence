package ooo

import _root_.circt.stage.ChiselStage

/** The same passive full-core probes, with the separate exact fused profile. */
class GuardedGuestFpFmaGsim extends GuardedGuestFpCoreGsim(fma = true)

object GuardedGuestFpFmaGsimMain extends App {
    require(args.length == 1, "output-directory")
    ChiselStage.emitCHIRRTLFile(new GuardedGuestFpFmaGsim, Array("--target-dir", args.head))
}
