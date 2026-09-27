package device

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.{TLPermissions, TLOpcode}
import soc.device.{TLError, TLROM}

class TLDeviceSpec extends AnyFunSuite with ChiselSim with TileLinkDeviceTestUtils {
    test("TLError returns denied responses for reads and writes") {
        simulate(new TLError(deviceParams)) { dut =>
            initTlSlave(dut.io.tl)
            dut.io.tl.d.ready.poke(true.B)

            readTl(dut.io.tl, dut.clock, address = 0x1000, source = 2, denied = true)

            writeTl(
                tl = dut.io.tl,
                clock = dut.clock,
                address = 0x1008,
                data = BigInt("0123456789abcdef", 16),
                mask = 0xff,
                source = 7,
                opcode = TLOpcode.PutFullData,
                denied = true
            )

            dut.io.tl.a.bits.opcode.poke(TLOpcode.AcquireBlock)
            dut.io.tl.a.bits.param.poke(TLPermissions.nToT)
            dut.io.tl.a.bits.size.poke(3.U)
            dut.io.tl.a.bits.source.poke(8.U)
            dut.io.tl.a.bits.address.poke("h1010".U)
            dut.io.tl.a.bits.mask.poke("hff".U)
            dut.io.tl.a.bits.data.poke(0.U)
            dut.io.tl.a.valid.poke(true.B)
            dut.io.tl.a.ready.expect(true.B)
            dut.clock.step()
            dut.io.tl.a.valid.poke(false.B)
            dut.io.tl.d.valid.expect(true.B)
            dut.io.tl.d.bits.opcode.expect(TLOpcode.GrantData)
            dut.io.tl.d.bits.param.expect(TLPermissions.nToT)
            dut.io.tl.d.bits.source.expect(8.U)
            dut.io.tl.d.bits.denied.expect(true.B)
            dut.clock.step()
        }
    }

    test("TLROM allows reads and denies writes") {
        simulate(new TLROM(deviceParams)) { dut =>
            initTlSlave(dut.io.tl)

            readTl(dut.io.tl, dut.clock, address = BigInt("80000000", 16), source = 1)
            acquireBlockTl(dut.io.tl, dut.clock, address = BigInt("80000000", 16), source = 3)

            writeTl(
                tl = dut.io.tl,
                clock = dut.clock,
                address = BigInt("80000008", 16),
                data = BigInt("0123456789abcdef", 16),
                mask = 0xff,
                source = 2,
                opcode = TLOpcode.PutFullData,
                denied = true
            )
        }
    }
}
