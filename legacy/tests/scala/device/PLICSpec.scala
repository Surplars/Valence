package device

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink._
import soc.device.interrupt.PLIC

class PLICSpec extends AnyFunSuite with ChiselSim {
    private val params = TLParams(addrWidth = 32, dataWidth = 64, sourceBits = 4, sinkBits = 1, sizeBits = 3)

    private def init(dut: PLIC): Unit = {
        dut.io.tl.a.valid.poke(false.B)
        dut.io.tl.a.bits.opcode.poke(0.U)
        dut.io.tl.a.bits.param.poke(0.U)
        dut.io.tl.a.bits.size.poke(3.U)
        dut.io.tl.a.bits.source.poke(0.U)
        dut.io.tl.a.bits.address.poke(0.U)
        dut.io.tl.a.bits.mask.poke("hff".U)
        dut.io.tl.a.bits.data.poke(0.U)
        dut.io.tl.a.bits.corrupt.poke(false.B)
        dut.io.tl.d.ready.poke(false.B)
        for (i <- 0 until dut.io.sources.length) {
            dut.io.sources(i).poke(false.B)
        }
    }

    private def write(dut: PLIC, address: BigInt, data: BigInt, mask: BigInt = 0xff): Unit = {
        val shift = ((address & 0x7) * 8).toInt
        dut.io.tl.d.ready.poke(true.B)
        dut.io.tl.a.bits.opcode.poke(TLOpcode.PutPartialData)
        dut.io.tl.a.bits.size.poke(3.U)
        dut.io.tl.a.bits.source.poke(2.U)
        dut.io.tl.a.bits.address.poke(address.U)
        dut.io.tl.a.bits.mask.poke((mask << (address & 0x7).toInt).U)
        dut.io.tl.a.bits.data.poke((data << shift).U)
        dut.io.tl.a.valid.poke(true.B)
        dut.io.tl.a.ready.expect(true.B)
        dut.clock.step()
        dut.io.tl.a.valid.poke(false.B)
        dut.io.tl.d.valid.expect(true.B)
        dut.io.tl.d.bits.opcode.expect(TLOpcode.AccessAck)
        dut.io.tl.d.bits.denied.expect(false.B)
        dut.clock.step()
    }

    private def read(dut: PLIC, address: BigInt): BigInt = {
        dut.io.tl.d.ready.poke(true.B)
        dut.io.tl.a.bits.opcode.poke(TLOpcode.Get)
        dut.io.tl.a.bits.size.poke(3.U)
        dut.io.tl.a.bits.source.poke(5.U)
        dut.io.tl.a.bits.address.poke(address.U)
        dut.io.tl.a.bits.mask.poke("hff".U)
        dut.io.tl.a.bits.data.poke(0.U)
        dut.io.tl.a.valid.poke(true.B)
        dut.io.tl.a.ready.expect(true.B)
        dut.clock.step()
        dut.io.tl.a.valid.poke(false.B)
        dut.io.tl.d.valid.expect(true.B)
        dut.io.tl.d.bits.opcode.expect(TLOpcode.AccessAckData)
        dut.io.tl.d.bits.denied.expect(false.B)
        val data = dut.io.tl.d.bits.data.peek().litValue
        dut.clock.step()
        data
    }

    private def readWord(dut: PLIC, address: BigInt): BigInt = {
        (read(dut, address) >> (((address & 0x7) * 8).toInt)) & 0xffffffffL
    }

    private def illegal(dut: PLIC, address: BigInt): Unit = {
        dut.io.tl.d.ready.poke(true.B)
        dut.io.tl.a.bits.opcode.poke(TLOpcode.Intent)
        dut.io.tl.a.bits.size.poke(3.U)
        dut.io.tl.a.bits.source.poke(9.U)
        dut.io.tl.a.bits.address.poke(address.U)
        dut.io.tl.a.bits.mask.poke("hff".U)
        dut.io.tl.a.bits.data.poke(0.U)
        dut.io.tl.a.valid.poke(true.B)
        dut.io.tl.a.ready.expect(true.B)
        dut.clock.step()
        dut.io.tl.a.valid.poke(false.B)
        dut.io.tl.d.valid.expect(true.B)
        dut.io.tl.d.bits.opcode.expect(TLOpcode.AccessAck)
        dut.io.tl.d.bits.source.expect(9.U)
        dut.io.tl.d.bits.denied.expect(true.B)
        dut.clock.step()
    }

    test("PLIC raises MEIP for enabled pending source and claim clears pending") {
        simulate(new PLIC(params, nSources = 4)) { dut =>
            init(dut)

            write(dut, 0x000004, 2)
            write(dut, 0x000008, 5)
            write(dut, 0x002000, 0x6)
            write(dut, 0x200000, 1)

            dut.io.sources(1).poke(true.B)
            dut.io.sources(2).poke(true.B)
            dut.clock.step()
            dut.io.sources(1).poke(false.B)
            dut.io.sources(2).poke(false.B)
            dut.io.meip.expect(true.B)
            dut.io.seip.expect(false.B)
            assert((readWord(dut, 0x001000) & 0x6) == 0x6)

            assert(readWord(dut, 0x200004) == 2)
            dut.io.meip.expect(true.B)
            assert((readWord(dut, 0x001000) & 0x6) == 0x2)

            assert(readWord(dut, 0x200004) == 1)
            dut.io.meip.expect(false.B)
        }
    }

    test("PLIC threshold gates notification without blocking claim") {
        simulate(new PLIC(params, nSources = 4)) { dut =>
            init(dut)

            write(dut, 0x000004, 3)
            write(dut, 0x002000, 0x2)
            write(dut, 0x200000, 3)
            dut.io.sources(1).poke(true.B)
            dut.clock.step()
            dut.io.sources(1).poke(false.B)

            dut.io.meip.expect(false.B)
            assert(readWord(dut, 0x200004) == 1)
        }
    }

    test("PLIC exposes an independent supervisor context") {
        simulate(new PLIC(params, nSources = 4)) { dut =>
            init(dut)

            write(dut, 0x000004, 4)
            write(dut, 0x002080, 0x2)   // S context enable word
            write(dut, 0x201000, 0)     // S context threshold
            dut.io.sources(1).poke(true.B)
            dut.clock.step()
            dut.io.sources(1).poke(false.B)

            dut.io.meip.expect(false.B)
            dut.io.seip.expect(true.B)
            assert(readWord(dut, 0x201004) == 1)
            dut.io.seip.expect(false.B)
        }
    }

    test("PLIC resolves equal priority sources by the lowest source ID") {
        simulate(new PLIC(params, nSources = 4)) { dut =>
            init(dut)

            write(dut, 0x000004, 3)
            write(dut, 0x000008, 3)
            write(dut, 0x002000, 0x6)
            write(dut, 0x200000, 0)

            dut.io.sources(1).poke(true.B)
            dut.io.sources(2).poke(true.B)
            dut.clock.step()
            dut.io.sources(1).poke(false.B)
            dut.io.sources(2).poke(false.B)

            dut.io.meip.expect(true.B)
            assert(readWord(dut, 0x200004) == 1)
            assert(readWord(dut, 0x200004) == 2)
            dut.io.meip.expect(false.B)
        }
    }

    test("PLIC level gateway redelivers only after completion") {
        simulate(new PLIC(params, nSources = 4)) { dut =>
            init(dut)

            write(dut, 0x000004, 3)
            write(dut, 0x002000, 0x2)
            write(dut, 0x200000, 0)

            dut.io.sources(1).poke(true.B)
            dut.clock.step()
            dut.io.meip.expect(true.B)
            assert(readWord(dut, 0x200004) == 1)

            dut.io.meip.expect(false.B)
            assert((readWord(dut, 0x001000) & 0x2) == 0)

            write(dut, 0x200004, 1)
            dut.io.meip.expect(true.B)
            assert(readWord(dut, 0x200004) == 1)

            dut.io.sources(1).poke(false.B)
            write(dut, 0x200004, 1)
            dut.io.meip.expect(false.B)
            assert((readWord(dut, 0x001000) & 0x2) == 0)
        }
    }

    test("PLIC denies unsupported TileLink opcodes") {
        simulate(new PLIC(params, nSources = 4)) { dut =>
            init(dut)
            illegal(dut, 0x200000)
        }
    }
}
