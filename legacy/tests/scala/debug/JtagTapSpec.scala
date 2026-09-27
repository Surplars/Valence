package debug

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.debug.{JtagInstruction, JtagTap}

class JtagTapSpec extends AnyFunSuite with ChiselSim {
    private def init(dut: JtagTap): Unit = {
        dut.io.jtag.tms.poke(true.B)
        dut.io.jtag.tck.poke(false.B)
        dut.io.jtag.tdi.poke(false.B)
        dut.io.dr_in.poke(0.U)
        dut.clock.step()
    }

    private def pulseTck(dut: JtagTap, tms: Boolean, tdi: Boolean = false): Boolean = {
        dut.io.jtag.tms.poke(tms.B)
        dut.io.jtag.tdi.poke(tdi.B)
        val tdo = dut.io.jtag.tdo.peek().litToBoolean
        dut.io.jtag.tck.poke(true.B)
        dut.clock.step()
        dut.io.jtag.tck.poke(false.B)
        dut.clock.step()
        tdo
    }

    private def resetTap(dut: JtagTap): Unit = {
        for (_ <- 0 until 5) pulseTck(dut, tms = true)
        pulseTck(dut, tms = false)
    }

    private def shiftIR(dut: JtagTap, value: Int, irLen: Int): Unit = {
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

    private def captureAndShiftDR(dut: JtagTap, bits: Int, input: BigInt = 0): BigInt = {
        pulseTck(dut, tms = true)
        pulseTck(dut, tms = false)
        pulseTck(dut, tms = false)

        var out = BigInt(0)
        for (i <- 0 until bits) {
            val inBit = ((input >> i) & 1) != 0
            if (pulseTck(dut, tms = i == bits - 1, tdi = inBit)) {
                out |= BigInt(1) << i
            }
        }
        pulseTck(dut, tms = true)
        pulseTck(dut, tms = false)
        out
    }

    test("TAP resets to IDCODE and shifts IDCODE data") {
        simulate(new JtagTap(irLen = 5, drLen = 64, idcode = 0x10e31913L)) { dut =>
            init(dut)
            resetTap(dut)
            dut.io.ir_out.expect(JtagInstruction.idcode(5))

            val idcode = captureAndShiftDR(dut, bits = 64)
            assert((idcode & ((BigInt(1) << 32) - 1)) == BigInt("10e31913", 16))
        }
    }

    test("BYPASS instruction shifts a single-bit data register") {
        simulate(new JtagTap(irLen = 5, drLen = 64, idcode = 0x10e31913L)) { dut =>
            init(dut)
            resetTap(dut)
            shiftIR(dut, value = (1 << 5) - 1, irLen = 5)
            dut.io.ir_out.expect(JtagInstruction.bypass(5))

            pulseTck(dut, tms = true)
            pulseTck(dut, tms = false)
            pulseTck(dut, tms = false)
            assert(!pulseTck(dut, tms = false, tdi = true))
            assert(pulseTck(dut, tms = true, tdi = false))
        }
    }

    test("Non-IDCODE data register updates from shifted data") {
        simulate(new JtagTap(irLen = 5, drLen = 64, idcode = 0x10e31913L)) { dut =>
            init(dut)
            resetTap(dut)
            shiftIR(dut, value = 0x11, irLen = 5)

            dut.io.dr_in.poke("h123456789a".U)
            val captured = captureAndShiftDR(dut, bits = 41, input = BigInt("15555555555", 16))
            assert(captured == BigInt("123456789a", 16))
            dut.io.dr_out.expect("h15555555555".U)
        }
    }

    test("DTMCS instruction exposes DMI width and version") {
        simulate(new JtagTap(irLen = 5, drLen = 64, idcode = 0x10e31913L)) { dut =>
            init(dut)
            resetTap(dut)
            shiftIR(dut, value = 0x10, irLen = 5)
            val dtmcs = captureAndShiftDR(dut, bits = 32)
            assert((dtmcs & 0xf) == 1)
            assert(((dtmcs >> 4) & 0x3f) == 7)
        }
    }
}
