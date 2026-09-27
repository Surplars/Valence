package device

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.TLOpcode
import soc.device.CLINT

class CLINTSpec extends AnyFunSuite with ChiselSim with TileLinkDeviceTestUtils {
    private def clintWrite(dut: CLINT, address: BigInt, mask: BigInt, data: BigInt): Unit = {
        writeTl(
            tl = dut.io.tl,
            clock = dut.clock,
            address = address,
            data = data,
            mask = mask,
            size = 2,
            source = 3
        )
    }

    private def clintRead(dut: CLINT, address: BigInt): BigInt =
        readTl(dut.io.tl, dut.clock, address, size = 3, source = 5)

    private def clintIllegal(dut: CLINT, address: BigInt): Unit = {
        writeTl(
            tl = dut.io.tl,
            clock = dut.clock,
            address = address,
            data = 0,
            mask = 0xff,
            size = 3,
            source = 9,
            opcode = TLOpcode.Intent,
            denied = true
        )
    }

    test("CLINT supports masked 32-bit access and denied unsupported opcodes") {
        simulate(new CLINT(deviceParams)) { dut =>
            initTlSlave(dut.io.tl)

            clintWrite(dut, address = 0x4004, mask = 0xf0, data = BigInt("1234567800000000", 16))
            clintWrite(dut, address = 0x4000, mask = 0x0f, data = BigInt("00000000deadbeef", 16))

            val fromLowAddress = clintRead(dut, 0x4000)
            assert(fromLowAddress == BigInt("12345678deadbeef", 16))

            val fromHighAddress = clintRead(dut, 0x4004)
            assert(fromHighAddress == BigInt("12345678deadbeef", 16))

            dut.io.msip.expect(false.B)
            clintWrite(dut, address = 0x0000, mask = 0x01, data = 1)
            dut.io.msip.expect(true.B)
            assert((clintRead(dut, 0x0000) & 1) == 1)
            clintWrite(dut, address = 0x0000, mask = 0x01, data = 0)
            dut.io.msip.expect(false.B)
            assert((clintRead(dut, 0x0000) & 1) == 0)

            clintIllegal(dut, 0x4000)
        }
    }
}
