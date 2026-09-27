package bus

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.{TLCoherenceHub, TLParams, TLPermissions, TLOpcode}

class TLCoherenceHubHarness(params: TLParams) extends Module {
    private val hubParams = params.copy(sourceBits = params.sourceBits + 1)

    val io = IO(new Bundle {
        val client0 = Flipped(new soc.bus.tilelink.TLBundle(params))
        val client1 = Flipped(new soc.bus.tilelink.TLBundle(params))
        val manager = new soc.bus.tilelink.TLBundle(hubParams)
    })

    val hub = Module(new TLCoherenceHub(params, nClients = 2, nEntries = 4))
    hub.io.clients(0) <> io.client0
    hub.io.clients(1) <> io.client1
    io.manager <> hub.io.manager
}

class TLCoherenceHubSpec extends AnyFunSuite with ChiselSim {
    private val params = TLParams(addrWidth = 32, dataWidth = 64, sourceBits = 4, sinkBits = 1, sizeBits = 3)

    private def initClient(tl: soc.bus.tilelink.TLBundle): Unit = {
        tl.a.valid.poke(false.B)
        tl.a.bits.opcode.poke(0.U)
        tl.a.bits.param.poke(0.U)
        tl.a.bits.size.poke(3.U)
        tl.a.bits.source.poke(0.U)
        tl.a.bits.address.poke(0.U)
        tl.a.bits.mask.poke("hff".U)
        tl.a.bits.data.poke(0.U)
        tl.a.bits.corrupt.poke(false.B)
        tl.b.ready.poke(true.B)
        tl.c.valid.poke(false.B)
        tl.c.bits.opcode.poke(0.U)
        tl.c.bits.param.poke(0.U)
        tl.c.bits.size.poke(3.U)
        tl.c.bits.source.poke(0.U)
        tl.c.bits.address.poke(0.U)
        tl.c.bits.data.poke(0.U)
        tl.c.bits.corrupt.poke(false.B)
        tl.d.ready.poke(true.B)
        tl.e.valid.poke(false.B)
        tl.e.bits.sink.poke(0.U)
    }

    private def initManager(tl: soc.bus.tilelink.TLBundle): Unit = {
        tl.a.ready.poke(true.B)
        tl.b.valid.poke(false.B)
        tl.b.bits.opcode.poke(0.U)
        tl.b.bits.param.poke(0.U)
        tl.b.bits.size.poke(3.U)
        tl.b.bits.source.poke(0.U)
        tl.b.bits.address.poke(0.U)
        tl.b.bits.mask.poke("hff".U)
        tl.b.bits.data.poke(0.U)
        tl.b.bits.corrupt.poke(false.B)
        tl.c.ready.poke(true.B)
        tl.d.valid.poke(false.B)
        tl.d.bits.opcode.poke(TLOpcode.GrantData)
        tl.d.bits.param.poke(TLPermissions.nToT)
        tl.d.bits.size.poke(3.U)
        tl.d.bits.source.poke(0.U)
        tl.d.bits.sink.poke(0.U)
        tl.d.bits.denied.poke(false.B)
        tl.d.bits.data.poke(0.U)
        tl.d.bits.corrupt.poke(false.B)
        tl.e.ready.poke(true.B)
    }

    private def issueAcquire(tl: soc.bus.tilelink.TLBundle, clock: Clock, source: Int, addr: BigInt): Unit = {
        tl.a.bits.opcode.poke(TLOpcode.AcquireBlock)
        tl.a.bits.param.poke(TLPermissions.nToT)
        tl.a.bits.size.poke(3.U)
        tl.a.bits.source.poke(source.U)
        tl.a.bits.address.poke(addr.U)
        tl.a.bits.mask.poke("hff".U)
        tl.a.bits.data.poke(0.U)
        tl.a.bits.corrupt.poke(false.B)
        tl.a.valid.poke(true.B)
        tl.a.ready.expect(true.B)
        clock.step()
        tl.a.valid.poke(false.B)
    }

    test("TLCoherenceHub probes old owner before granting a conflicting acquire") {
        simulate(new TLCoherenceHubHarness(params)) { dut =>
            initClient(dut.io.client0)
            initClient(dut.io.client1)
            initManager(dut.io.manager)

            issueAcquire(dut.io.client0, dut.clock, source = 2, addr = 0x1000)
            dut.io.manager.a.valid.expect(true.B)
            dut.io.manager.a.bits.source.expect("b00010".U)
            dut.clock.step()

            dut.io.manager.d.bits.source.poke("b00010".U)
            dut.io.manager.d.bits.data.poke("haaaa5555cccc3333".U)
            dut.io.manager.d.valid.poke(true.B)
            dut.io.client0.d.valid.expect(true.B)
            dut.io.client0.d.bits.opcode.expect(TLOpcode.GrantData)
            dut.io.client0.d.bits.source.expect(2.U)
            dut.io.client0.d.bits.data.expect("haaaa5555cccc3333".U)
            dut.clock.step()
            dut.io.manager.d.valid.poke(false.B)

            issueAcquire(dut.io.client1, dut.clock, source = 4, addr = 0x1000)
            dut.io.client0.b.valid.expect(true.B)
            dut.io.client0.b.bits.opcode.expect(TLOpcode.ProbeBlock)
            dut.io.client0.b.bits.source.expect(4.U)
            dut.io.client0.b.bits.address.expect("h1000".U)
            dut.io.manager.a.valid.expect(false.B)
            dut.clock.step()

            dut.io.client0.c.bits.opcode.poke(TLOpcode.ProbeAckData)
            dut.io.client0.c.bits.param.poke(TLPermissions.toN)
            dut.io.client0.c.bits.size.poke(3.U)
            dut.io.client0.c.bits.source.poke(4.U)
            dut.io.client0.c.bits.address.poke("h1000".U)
            dut.io.client0.c.bits.data.poke("h1111222233334444".U)
            dut.io.client0.c.bits.corrupt.poke(false.B)
            dut.io.client0.c.valid.poke(true.B)
            dut.io.client0.c.ready.expect(true.B)
            dut.clock.step()
            dut.io.client0.c.valid.poke(false.B)

            dut.io.manager.c.valid.expect(true.B)
            dut.io.manager.c.bits.opcode.expect(TLOpcode.ReleaseData)
            dut.io.manager.c.bits.source.expect("b00100".U)
            dut.io.manager.c.bits.address.expect("h1000".U)
            dut.io.manager.c.bits.data.expect("h1111222233334444".U)
            dut.clock.step()

            dut.io.manager.d.bits.opcode.poke(TLOpcode.ReleaseAck)
            dut.io.manager.d.bits.source.poke("b00100".U)
            dut.io.manager.d.bits.data.poke(0.U)
            dut.io.manager.d.valid.poke(true.B)
            dut.clock.step()
            dut.io.manager.d.valid.poke(false.B)

            dut.io.client1.d.valid.expect(true.B)
            dut.io.client1.d.bits.opcode.expect(TLOpcode.GrantData)
            dut.io.client1.d.bits.param.expect(TLPermissions.nToT)
            dut.io.client1.d.bits.source.expect(4.U)
            dut.io.client1.d.bits.data.expect("h1111222233334444".U)
            dut.io.manager.a.valid.expect(false.B)
            dut.clock.step()

            issueAcquire(dut.io.client0, dut.clock, source = 3, addr = 0x1000)
            dut.io.client1.b.valid.expect(true.B)
            dut.io.client1.b.bits.source.expect(3.U)
            dut.io.manager.a.valid.expect(false.B)
        }
    }
}
