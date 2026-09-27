package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.timer.MachineTimer

class TimerParamsSpec extends AnyFunSuite {
    test("timer requires aligned disjoint registers and permits relocated windows") {
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new MachineTimer(compareAddress = 1)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new MachineTimer(timeAddress = BigInt(1) << 64)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new MachineTimer(0x1000, 0x1000)) }
        assert(ChiselStage.emitCHIRRTL(new MachineTimer(0x1000, 0x2000)).contains("module MachineTimer"))
    }
}
