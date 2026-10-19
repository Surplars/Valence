package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.clock.ManagedPeripheralBank
import soc.ip.ethernet.TriSpeedManagedGmac

/** Merge guard: preserve each existing clock profile without qualifying a new combination. */
class SharedPeripheralProfileSpec extends AnyFunSuite {
    private def mac(handoff: Boolean, balanced: Boolean): String =
        ChiselStage.emitCHIRRTL(new TriSpeedManagedGmac(
            rawClockHandoff = handoff, balancedRawClock = balanced))

    test("shared MAC retains default, main handoff and I1 balanced profiles independently") {
        val default = mac(false, false)
        val handoff = mac(true, false)
        val balanced = mac(false, true)
        assert(!default.contains(" of MacRawHandoff"))
        assert(!default.contains(" of ContinuousClockBuffer"))
        assert(handoff.contains(" of MacRawHandoff"))
        assert(!handoff.contains(" of ContinuousClockBuffer"))
        assert(!balanced.contains(" of MacRawHandoff"))
        assert(balanced.contains(" of ContinuousClockBuffer"))
    }

    test("shared bank forwards each existing tri-speed profile") {
        for ((handoff, balanced) <- Seq((false, false), (true, false), (false, true))) {
            val fir = ChiselStage.emitCHIRRTL(new ManagedPeripheralBank(
                ManagedPeripheralTestConfig.params, triSpeedEthernet = true, triSpeedTxFrameSlots = 2,
                triSpeedRawClockHandoff = handoff, balancedRawClocks = balanced))
            assert(fir.contains(" of MacRawHandoff") == handoff)
            assert(fir.contains(" of ContinuousClockBuffer") == balanced)
        }
    }

    test("existing hardware and endpoint clock constraints remain enforced") {
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new TriSpeedManagedGmac(hardwareClocks = false, balancedRawClock = true))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new ManagedPeripheralBank(
                ManagedPeripheralTestConfig.params, balancedRawClocks = true))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new ManagedPeripheralBank(
                ManagedPeripheralTestConfig.params, triSpeedRawClockHandoff = true))
        }
    }

    test("unqualified combined clock profile fails before hardware is constructed") {
        val macError = intercept[IllegalArgumentException] { mac(true, true) }
        assert(macError.getMessage.contains("lifecycle/CDC qualification"))
        val bankError = intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new ManagedPeripheralBank(
                ManagedPeripheralTestConfig.params, triSpeedEthernet = true, triSpeedTxFrameSlots = 2,
                triSpeedRawClockHandoff = true, balancedRawClocks = true))
        }
        assert(bankError.getMessage.contains("lifecycle/CDC qualification"))
    }
}
