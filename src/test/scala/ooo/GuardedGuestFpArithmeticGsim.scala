package ooo

import _root_.circt.stage.ChiselStage

/** The same passive full-core probes, with the separate exact arithmetic profile. */
class GuardedGuestFpArithmeticGsim extends GuardedGuestFpCoreGsim(arithmetic = true)

object GuardedGuestFpArithmeticGsimMain extends App {
    require(args.length == 1, "output-directory")
    ChiselStage.emitCHIRRTLFile(new GuardedGuestFpArithmeticGsim, Array("--target-dir", args.head))
}
