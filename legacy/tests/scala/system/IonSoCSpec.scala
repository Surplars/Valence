package system

import chisel3.simulator.scalatest.ChiselSim
import chisel3._
import org.scalatest.funsuite.AnyFunSuite
import soc.IonSoC
import soc.config.{ISAProfiles, InterruptControllerKind, SoCFeatures, SoCProfiles}
import soc.debug.DebugModuleMap
import soc.isa.Extension

class IonSoCSpec extends AnyFunSuite with ChiselSim {
    private def tieOffExternalInterrupts(dut: IonSoC): Unit = {
        for (i <- 0 until dut.io.ext_irq_sources.length) {
            dut.io.ext_irq_sources(i).poke(false)
        }
        dut.io.uart_rx_valid.poke(false)
        dut.io.uart_rx_byte.poke(0)
        dut.io.jtag_tms.poke(true)
        dut.io.jtag_tck.poke(false)
        dut.io.jtag_tdi.poke(false)
    }

    test("IonSoC elaborates with instruction cache enabled") {
        simulate(new IonSoC(SoCFeatures(iCache = true))) { dut => tieOffExternalInterrupts(dut) }
    }

    test("IonSoC elaborates the fixed bare-metal MCU profile") {
        simulate(new IonSoC(SoCProfiles.BareMetalMCU, ISAProfiles.RV64IMACB)) { dut => tieOffExternalInterrupts(dut) }
    }

    test("IonSoC elaborates with optional MMIO devices disabled") {
        simulate(new IonSoC(SoCFeatures(uart = false, clint = false, interruptController = InterruptControllerKind.None))) { dut =>
            tieOffExternalInterrupts(dut)
        }
    }

    test("IonSoC elaborates with feature and ISA extension overrides") {
        simulate(new IonSoC(SoCFeatures(mmu = true, iCache = true, dCache = false), Set(Extension.RV64I, Extension.Zicsr))) { dut =>
            tieOffExternalInterrupts(dut)
        }
    }

    test("IonSoC elaborates with AIA placeholder configuration") {
        simulate(new IonSoC(SoCFeatures(interruptController = InterruptControllerKind.AIA))) { dut => tieOffExternalInterrupts(dut) }
    }

    test("Debug halt request freezes and resume releases the core PC") {
        // Keep this slow JTAG/debug test on a direct-fetch frontend. The fixed
        // MCU profile has I-cache enabled, while this test only needs the TAP,
        // DM, and PC halt/resume contract.
        simulate(new IonSoC(SoCFeatures(iCache = false))) { dut =>
            tieOffExternalInterrupts(dut)
            resetTap(dut)
            shiftIR(dut, value = 0x11, irLen = 5)

            dut.clock.step(4)
            val runningPc = dut.io.debug.pc.peek().litValue

            dmiWrite(dut, DebugModuleMap.DMControl, BigInt("80000001", 16))
            val haltedPc = waitStablePc(dut)
            dut.clock.step(8)
            dut.io.debug.pc.expect(haltedPc.U)

            dmiWrite(dut, DebugModuleMap.DMControl, BigInt("40000001", 16))
            dut.clock.step(6)
            assert(dut.io.debug.pc.peek().litValue != haltedPc)
        }
    }

    private def pulseTck(dut: IonSoC, tms: Boolean, tdi: Boolean = false): Boolean = {
        dut.io.jtag_tms.poke(tms.B)
        dut.io.jtag_tdi.poke(tdi.B)
        val tdo = dut.io.jtag_tdo.peek().litToBoolean
        dut.io.jtag_tck.poke(true.B)
        dut.clock.step()
        dut.io.jtag_tck.poke(false.B)
        dut.clock.step()
        tdo
    }

    private def resetTap(dut: IonSoC): Unit = {
        for (_ <- 0 until 5) pulseTck(dut, tms = true)
        pulseTck(dut, tms = false)
    }

    private def shiftIR(dut: IonSoC, value: Int, irLen: Int): Unit = {
        pulseTck(dut, tms = true)
        pulseTck(dut, tms = true)
        pulseTck(dut, tms = false)
        pulseTck(dut, tms = false)
        for (i <- 0 until irLen) {
            pulseTck(dut, tms = i == irLen - 1, tdi = ((value >> i) & 1) != 0)
        }
        pulseTck(dut, tms = true)
        pulseTck(dut, tms = false)
    }

    private def dmiWrite(dut: IonSoC, addr: Int, data: BigInt): Unit = {
        val packet = (BigInt(addr) << 34) | ((data & BigInt("ffffffff", 16)) << 2) | 2
        pulseTck(dut, tms = true)
        pulseTck(dut, tms = false)
        pulseTck(dut, tms = false)
        for (i <- 0 until 41) {
            pulseTck(dut, tms = i == 40, tdi = ((packet >> i) & 1) != 0)
        }
        pulseTck(dut, tms = true)
        pulseTck(dut, tms = false)
    }

    private def waitStablePc(dut: IonSoC, maxCycles: Int = 32): BigInt = {
        var stable = 0
        var last = dut.io.debug.pc.peek().litValue
        for (_ <- 0 until maxCycles if stable < 4) {
            dut.clock.step()
            val now = dut.io.debug.pc.peek().litValue
            if (now == last) {
                stable += 1
            } else {
                stable = 0
                last = now
            }
        }
        assert(stable >= 4, "PC did not become stable after debug halt request")
        last
    }
}
