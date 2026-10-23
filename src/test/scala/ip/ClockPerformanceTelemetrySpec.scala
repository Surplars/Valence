package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.clock._

class ClockPerformanceTelemetrySpec extends AnyFunSuite {
    test("actual edge telemetry elaborates with complete MMIO CDC and no rate metadata") {
        val fir = ChiselStage.emitCHIRRTL(new ClockPerformanceTelemetry())
        assert(fir.contains("TelemetryGrayCounterBank"))
        assert(fir.contains("RegisterClockDomainBridge"))
        assert(fir.contains("graySync0") && fir.contains("graySync1"))
        assert(!fir.contains("actualHz") && !fir.contains("ClockRateControl"))
    }
}

/** Small-width real RTL fixture deliberately exercises natural modulo wraps. */
object ClockPerformanceTelemetryMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new ClockPerformanceTelemetry(windowCycles = 128, width = 10),
        Array("--target-dir", args(0)), firtoolOpts = Array("-disable-all-randomization", "-strip-debug-info",
            "-default-layer-specialization=disable", "--lowering-options=disallowLocalVariables,disallowPackedArrays"))
}
