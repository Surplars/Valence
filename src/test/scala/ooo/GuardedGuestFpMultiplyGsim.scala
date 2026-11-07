package ooo

import _root_.circt.stage.ChiselStage

/** The same passive full-core probes, with the separate exact multiplication profile. */
class GuardedGuestFpMultiplyGsim extends GuardedGuestFpCoreGsim(multiply = true)

object GuardedGuestFpMultiplyGsimMain extends App {
    require(args.length == 1, "output-directory")
    ChiselStage.emitCHIRRTLFile(new GuardedGuestFpMultiplyGsim, Array("--target-dir", args.head))
}
