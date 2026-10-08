package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class FloatingPointResourceSpec extends AnyFunSuite {
    test("FPGA resources preserve complete F/D and recover the exact baseline configuration") {
        val base = FloatingPointConfig.fullFD
        val fpga = base.copy(resources = FloatingPointResourceConfig.fpga)
        assert(base.complete && fpga.complete && fpga.f && fpga.d)
        assert(fpga.copy(resources = FloatingPointResourceConfig.baseline) == base)
        assert(!base.resources.committedStateMemory && !base.resources.sharedFormatRounders)
    }
    test("committed FPGA state is an unreset 32x64 asynchronous memory with validity") {
        val p = OooParams(machineSystem = true, floatingPoint = FloatingPointConfig.fullFD.copy(resources = FloatingPointResourceConfig.fpga))
        val fir = ChiselStage.emitCHIRRTL(new FloatingPointState(p))
        assert("cmem".r.findAllIn(fir).length == 1, fir)
        assert(fir.contains("UInt<64>[32]") && !fir.contains("smem"), fir)
        assert(fir.contains("initialized") && !fir.contains("registerPayload"), fir)
    }
    test("shared format raw stage removes six duplicated arithmetic rounders") {
        for (shared <- Seq(false, true)) {
            val c = FloatingPointConfig.fullFD.copy(resources = FloatingPointResourceConfig(sharedFormatRounders = shared))
            val fir = ChiselStage.emitCHIRRTL(new FloatingPointExecute(OooParams(), c))
            val arithmeticInstances = "inst round of RoundRawFNToRecFN".r.findAllIn(fir).length
            assert(arithmeticInstances == (if (shared) 2 else 8), s"rounder instances=$arithmeticInstances")
            assert(fir.contains("module FloatingPointSharedArithmeticS") == shared)
            assert(fir.contains("module FloatingPointSharedArithmeticD") == shared)
        }
    }
    test("shared multiply/FMA keeps exactly one full significand multiplier per format") {
        for (mode <- Seq("baseline", "round", "fpga")) {
            val c = FloatingPointConfig.fullFD.copy(resources = FloatingPointResourceConfig.named(mode))
            val fir = ChiselStage.emitCHIRRTL(new FloatingPointExecute(OooParams(), c))
            val multipliers = fir.linesIterator.count(_.contains(" = mul("))
            assert(multipliers == (if (mode == "fpga") 2 else 4), s"$mode multipliers=$multipliers")
        }
        intercept[IllegalArgumentException] { FloatingPointResourceConfig(sharedMultiplyFused = true) }
    }

}

/** The normalized RTL has no CPU debug read ports and uses production contracts. */
object FloatingPointResourceRtlMain extends App {
    val resources = FloatingPointResourceConfig.named(args.lift(1).getOrElse("baseline"))
    val p = OooParams(robEntries = 16, tagBits = 64, machineSystem = true,
        floatingPoint = FloatingPointConfig.fullFD.copy(resources = resources))
    val options = Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    ChiselStage.emitSystemVerilogFile(new FloatingPointState(p),
        Array("--target-dir", args.head + "/state"), options)
    ChiselStage.emitSystemVerilogFile(new FloatingPointExecute(p, p.fpConfig),
        Array("--target-dir", args.head + "/execute"), options)
}
