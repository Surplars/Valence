package debug

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.debug._

class HartDebugContractSpec extends AnyFunSuite {
    test("abstract register numbers are explicit and GPR bounds fail closed") {
        assert(HartDebugContract.version == 1)
        assert((0 until 32).map(HartDebugContract.gpr) == (0x1000 to 0x101f))
        intercept[IllegalArgumentException](HartDebugContract.gpr(-1))
        intercept[IllegalArgumentException](HartDebugContract.gpr(32))
        assert(Seq(HartDebugContract.Dcsr, HartDebugContract.Dpc,
            HartDebugContract.Dscratch0, HartDebugContract.Dscratch1) == Seq(0x7b0, 0x7b1, 0x7b2, 0x7b3))
        assert(Seq(HartDebugContract.Tselect, HartDebugContract.Tdata1,
            HartDebugContract.Tdata2, HartDebugContract.Tdata3, HartDebugContract.Tinfo) ==
            Seq(0x7a0, 0x7a1, 0x7a2, 0x7a3, 0x7a4))
    }
    test("internal command and result encodings cannot alias success or each other") {
        val commands = Seq(HartDebugContract.Halt, HartDebugContract.Resume,
            HartDebugContract.Step, HartDebugContract.AccessRegister)
        val results = Seq(HartDebugContract.Success, HartDebugContract.Unavailable,
            HartDebugContract.Unsupported, HartDebugContract.WrongState,
            HartDebugContract.Exception, HartDebugContract.StaleEpoch)
        assert(commands.distinct.size == commands.size && commands.forall(_ < 8))
        assert(results.distinct.size == results.size && results.forall(_ < 8))
    }
    test("unavailable adapter exposes typed handshake, never halt or precise success") {
        val text = ChiselStage.emitCHIRRTL(new HartDebugUnavailable)
        assert(text.contains("registerNumber : UInt<16>"))
        assert(text.contains("retirementSequence : UInt<64>"))
        assert(text.contains("connect io.available, UInt<1>(0h0)"))
        assert(text.contains("connect io.halted, UInt<1>(0h0)"))
        assert(text.contains("connect io.preciseStop.valid, UInt<1>(0h0)"))
        assert(text.contains("connect io.completion.bits.result, UInt<1>(0h1)"))
        assert(text.contains("regreset pending") && text.contains("connect io.completion.valid, pending"))
        assert(!text.contains("extmodule") && !text.contains("dmi") && !text.contains("haltRequest"))
    }
    test("default transport is still absent with no hart adapter or CPU fanout") {
        val text = ChiselStage.emitCHIRRTL(new JtagDebugReservation())
        assert(!text.contains("HartDebug") && !text.contains("reg ") && !text.contains("regreset "))
        assert(!text.contains("extmodule") && !text.contains("inst "))
    }
}
