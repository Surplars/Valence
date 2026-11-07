package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Pure configuration checks, not hardware simulation. */
class GuestSstcConfigSpec extends AnyFunSuite {
    test("guest timer support does not enable the experimental H assembly by default") {
        assert(!OooParams().hypervisorExperiment)
        assert(!BoardSocConfig.boardParams(BoardSocConfig.timingProfile).hypervisorExperiment)
    }

    test("the experimental timer path does not advertise complete H support") {
        val experiment = OooParams(hypervisorExperiment = true, machineSystem = true,
            virtualMemoryLevels = 3, pmpEntries = 16)
        assert((experiment.misaValue & (BigInt(1) << 7)) == 0)
        assert((OooParams().misaValue & (BigInt(1) << 7)) == 0)
    }
}
