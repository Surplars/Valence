package device

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.device.UartTx

class UartSpec extends AnyFunSuite with ChiselSim with TileLinkDeviceTestUtils {
    private def init(dut: UartTx): Unit = {
        initTlSlave(dut.io.tl, size = 0)
        dut.io.rx_valid.poke(false.B)
        dut.io.rx_byte.poke(0.U)
    }

    private def writeByte(dut: UartTx, address: BigInt, data: BigInt, expectTx: Option[BigInt] = None): Unit = {
        val lane = (address & 0x7).toInt
        dut.io.tl.d.ready.poke(true.B)
        dut.io.tl.a.bits.opcode.poke(soc.bus.tilelink.TLOpcode.PutPartialData)
        dut.io.tl.a.bits.param.poke(0.U)
        dut.io.tl.a.bits.size.poke(0.U)
        dut.io.tl.a.bits.source.poke(4.U)
        dut.io.tl.a.bits.address.poke(address.U)
        dut.io.tl.a.bits.mask.poke((1 << lane).U)
        dut.io.tl.a.bits.data.poke((data << (lane * 8)).U)
        dut.io.tl.a.bits.corrupt.poke(false.B)
        dut.io.tl.a.valid.poke(true.B)
        dut.io.tl.a.ready.expect(true.B)
        dut.clock.step()
        dut.io.tl.a.valid.poke(false.B)
        expectTx.foreach { byte =>
            dut.io.tx_valid.expect(true.B)
            dut.io.tx_byte.expect(byte.U)
        }
        dut.io.tl.d.valid.expect(true.B)
        dut.io.tl.d.bits.opcode.expect(soc.bus.tilelink.TLOpcode.AccessAck)
        dut.io.tl.d.bits.source.expect(4.U)
        dut.io.tl.d.bits.denied.expect(false.B)
        dut.clock.step()
    }

    private def readByte(dut: UartTx, address: BigInt): BigInt =
        readTlByte(dut.io.tl, dut.clock, address)

    test("UART exposes a 16550-style register subset and interrupt state") {
        simulate(new UartTx(deviceParams)) { dut =>
            init(dut)

            writeByte(dut, 0x0, 'A', Some('A'))
            dut.io.tx_valid.expect(false.B)

            assert(readByte(dut, 0x5) == 0x60)
            assert(readByte(dut, 0x2) == 0x01)
            writeByte(dut, 0x7, 0x5a)
            assert(readByte(dut, 0x7) == 0x5a)

            writeByte(dut, 0x3, 0x80)
            writeByte(dut, 0x0, 0x34)
            writeByte(dut, 0x1, 0x12)
            assert(readByte(dut, 0x0) == 0x34)
            assert(readByte(dut, 0x1) == 0x12)
            writeByte(dut, 0x3, 0x03)
            assert(readByte(dut, 0x3) == 0x03)
            assert(readByte(dut, 0x1) == 0x00)

            writeByte(dut, 0x1, 0x01)
            dut.io.rx_byte.poke('R'.U)
            dut.io.rx_valid.poke(true.B)
            dut.clock.step()
            dut.io.rx_valid.poke(false.B)
            dut.io.irq.expect(true.B)
            assert(readByte(dut, 0x2) == 0x04)
            assert(readByte(dut, 0x5) == 0x61)
            assert(readByte(dut, 0x0) == 'R')
            dut.io.irq.expect(false.B)

            writeByte(dut, 0x1, 0x02)
            dut.io.irq.expect(true.B)
            assert(readByte(dut, 0x2) == 0x02)
            dut.io.irq.expect(false.B)
        }
    }
}
