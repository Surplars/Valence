package bus

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.{TLParams, TLSystemXbar, TLOpcode}

class TLSystemXbarHarness(params: TLParams) extends Module {
    val io = IO(new Bundle {
        val master0 = Flipped(new soc.bus.tilelink.TLBundle(params))
        val master1 = Flipped(new soc.bus.tilelink.TLBundle(params))
        val slave = new soc.bus.tilelink.TLBundle(params.copy(sourceBits = params.sourceBits + 1))
    })

    val xbar = Module(new TLSystemXbar(params, nMasters = 2))
    xbar.io.masters(0) <> io.master0
    xbar.io.masters(1) <> io.master1
    io.slave <> xbar.io.slave
}

class TLSystemXbarSpec extends AnyFunSuite with ChiselSim {
    private val params = TLParams(addrWidth = 32, dataWidth = 64, sourceBits = 4, sinkBits = 1, sizeBits = 3)

    private def initBundle(tl: soc.bus.tilelink.TLBundle): Unit = {
        tl.a.valid.poke(false.B)
        tl.a.bits.opcode.poke(0.U)
        tl.a.bits.param.poke(0.U)
        tl.a.bits.size.poke(3.U)
        tl.a.bits.source.poke(0.U)
        tl.a.bits.address.poke(0.U)
        tl.a.bits.mask.poke("hff".U)
        tl.a.bits.data.poke(0.U)
        tl.a.bits.corrupt.poke(false.B)
        tl.b.ready.poke(false.B)
        tl.c.valid.poke(false.B)
        tl.c.bits.opcode.poke(0.U)
        tl.c.bits.param.poke(0.U)
        tl.c.bits.size.poke(3.U)
        tl.c.bits.source.poke(0.U)
        tl.c.bits.address.poke(0.U)
        tl.c.bits.data.poke(0.U)
        tl.c.bits.corrupt.poke(false.B)
        tl.d.ready.poke(false.B)
        tl.e.valid.poke(false.B)
        tl.e.bits.sink.poke(0.U)
    }

    test("TLSystemXbar preserves source tags and routes B/D coherence channels") {
        simulate(new TLSystemXbarHarness(params)) { dut =>
            initBundle(dut.io.master0)
            initBundle(dut.io.master1)
            dut.io.slave.a.ready.poke(true.B)
            dut.io.slave.b.valid.poke(false.B)
            dut.io.slave.b.bits.opcode.poke(TLOpcode.ProbeBlock)
            dut.io.slave.b.bits.param.poke(0.U)
            dut.io.slave.b.bits.size.poke(3.U)
            dut.io.slave.b.bits.source.poke(0.U)
            dut.io.slave.b.bits.address.poke(0.U)
            dut.io.slave.b.bits.mask.poke("hff".U)
            dut.io.slave.b.bits.data.poke(0.U)
            dut.io.slave.b.bits.corrupt.poke(false.B)
            dut.io.slave.c.ready.poke(true.B)
            dut.io.slave.d.valid.poke(false.B)
            dut.io.slave.d.bits.opcode.poke(TLOpcode.AccessAckData)
            dut.io.slave.d.bits.param.poke(0.U)
            dut.io.slave.d.bits.size.poke(3.U)
            dut.io.slave.d.bits.source.poke(0.U)
            dut.io.slave.d.bits.sink.poke(0.U)
            dut.io.slave.d.bits.denied.poke(false.B)
            dut.io.slave.d.bits.data.poke(0.U)
            dut.io.slave.d.bits.corrupt.poke(false.B)
            dut.io.slave.e.ready.poke(true.B)

            dut.io.master1.a.bits.opcode.poke(TLOpcode.AcquireBlock)
            dut.io.master1.a.bits.source.poke(5.U)
            dut.io.master1.a.bits.address.poke("h1000".U)
            dut.io.master1.a.valid.poke(true.B)
            dut.io.master1.a.ready.expect(true.B)
            dut.io.slave.a.valid.expect(true.B)
            dut.io.slave.a.bits.source.expect("b10101".U)
            dut.clock.step()
            dut.io.master1.a.valid.poke(false.B)

            dut.io.master1.d.ready.poke(true.B)
            dut.io.slave.d.bits.source.poke("b10101".U)
            dut.io.slave.d.bits.data.poke("h1122334455667788".U)
            dut.io.slave.d.valid.poke(true.B)
            dut.io.master0.d.valid.expect(false.B)
            dut.io.master1.d.valid.expect(true.B)
            dut.io.master1.d.bits.source.expect(5.U)
            dut.io.master1.d.bits.data.expect("h1122334455667788".U)
            dut.io.slave.d.ready.expect(true.B)
            dut.clock.step()
            dut.io.slave.d.valid.poke(false.B)

            dut.io.master1.b.ready.poke(true.B)
            dut.io.slave.b.bits.source.poke("b10101".U)
            dut.io.slave.b.bits.address.poke("h1000".U)
            dut.io.slave.b.valid.poke(true.B)
            dut.io.master0.b.valid.expect(false.B)
            dut.io.master1.b.valid.expect(true.B)
            dut.io.master1.b.bits.source.expect(5.U)
            dut.io.master1.b.bits.address.expect("h1000".U)
            dut.io.slave.b.ready.expect(true.B)
            dut.clock.step()
            dut.io.slave.b.valid.poke(false.B)

            dut.io.master0.c.bits.opcode.poke(TLOpcode.ProbeAck)
            dut.io.master0.c.bits.source.poke(3.U)
            dut.io.master0.c.bits.address.poke("h2000".U)
            dut.io.master0.c.valid.poke(true.B)
            dut.io.master0.c.ready.expect(true.B)
            dut.io.slave.c.valid.expect(true.B)
            dut.io.slave.c.bits.source.expect("b00011".U)
            dut.clock.step()
            dut.io.master0.c.valid.poke(false.B)

            dut.io.master1.e.bits.sink.poke(1.U)
            dut.io.master1.e.valid.poke(true.B)
            dut.io.master1.e.ready.expect(true.B)
            dut.io.slave.e.valid.expect(true.B)
            dut.io.slave.e.bits.sink.expect(1.U)
            dut.clock.step()
        }
    }
}
