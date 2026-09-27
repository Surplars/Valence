package core

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.TLParams
import soc.core.DcachePtwArbiter
import soc.memory.cache.CacheCmd

class DcachePtwArbiterSpec extends AnyFunSuite with ChiselSim {
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4, sinkBits = 1, sizeBits = 3)

    private def init(dut: DcachePtwArbiter): Unit = {
        dut.io.ifetchPtwReq.valid.poke(false.B)
        dut.io.ifetchPtwReq.bits.addr.poke(0.U)
        dut.io.ifetchPtwReq.bits.vaddr.poke(0.U)
        dut.io.ifetchPtwReq.bits.cmd.poke(CacheCmd.Read)
        dut.io.ifetchPtwReq.bits.wdata.poke(0.U)
        dut.io.ifetchPtwReq.bits.mask.poke("hff".U)
        dut.io.ifetchPtwReq.bits.size.poke(3.U)
        dut.io.ifetchPtwReq.bits.signed.poke(false.B)
        dut.io.ifetchPtwReq.bits.fence.poke(false.B)
        dut.io.ifetchPtwReq.bits.fencei.poke(false.B)
        dut.io.ifetchPtwReq.bits.atomic.poke(false.B)
        dut.io.ifetchPtwReq.bits.cacheable.poke(true.B)
        dut.io.ifetchPtwReq.bits.device.poke(false.B)
        dut.io.ifetchPtwResp.ready.poke(true.B)

        dut.io.lsuReq.valid.poke(false.B)
        dut.io.lsuReq.bits.addr.poke(0.U)
        dut.io.lsuReq.bits.vaddr.poke(0.U)
        dut.io.lsuReq.bits.cmd.poke(CacheCmd.Read)
        dut.io.lsuReq.bits.wdata.poke(0.U)
        dut.io.lsuReq.bits.mask.poke(0.U)
        dut.io.lsuReq.bits.size.poke(0.U)
        dut.io.lsuReq.bits.signed.poke(false.B)
        dut.io.lsuReq.bits.fence.poke(false.B)
        dut.io.lsuReq.bits.fencei.poke(false.B)
        dut.io.lsuReq.bits.atomic.poke(false.B)
        dut.io.lsuReq.bits.cacheable.poke(false.B)
        dut.io.lsuReq.bits.device.poke(false.B)
        dut.io.lsuResp.ready.poke(true.B)

        dut.io.cacheReq.ready.poke(false.B)
        dut.io.cacheResp.valid.poke(false.B)
        dut.io.cacheResp.bits.rdata.poke(0.U)
        dut.io.cacheResp.bits.err.poke(false.B)
        dut.io.maintPending.poke(false.B)
    }

    test("keeps PTW response ownership when cache ready returns before response") {
        simulate(new DcachePtwArbiter(params)) { dut =>
            init(dut)

            dut.io.ifetchPtwReq.valid.poke(true.B)
            dut.io.ifetchPtwReq.bits.addr.poke("h402f5ff0".U)
            dut.io.cacheReq.ready.poke(true.B)
            dut.io.cacheReq.valid.expect(true.B)
            dut.io.ifetchPtwReq.ready.expect(true.B)
            dut.clock.step()

            dut.io.ifetchPtwReq.valid.poke(false.B)
            dut.io.cacheReq.ready.poke(true.B)
            dut.io.cacheResp.valid.poke(false.B)
            dut.io.respPending.expect(true.B)
            dut.io.respOwnerPtw.expect(true.B)
            dut.clock.step(2)
            dut.io.respPending.expect(true.B)
            dut.io.respOwnerPtw.expect(true.B)

            dut.io.cacheResp.valid.poke(true.B)
            dut.io.cacheResp.bits.rdata.poke("h1122334455667788".U)
            dut.io.ifetchPtwResp.valid.expect(true.B)
            dut.io.ifetchPtwResp.bits.rdata.expect("h1122334455667788".U)
            dut.io.lsuResp.valid.expect(false.B)
            dut.clock.step()

            dut.io.cacheResp.valid.poke(false.B)
            dut.io.respPending.expect(false.B)
        }
    }

    test("clears outstanding ownership when maintenance drains a cache response") {
        simulate(new DcachePtwArbiter(params)) { dut =>
            init(dut)

            dut.io.ifetchPtwReq.valid.poke(true.B)
            dut.io.ifetchPtwReq.bits.addr.poke("h402f5ff0".U)
            dut.io.cacheReq.ready.poke(true.B)
            dut.clock.step()

            dut.io.ifetchPtwReq.valid.poke(false.B)
            dut.io.maintPending.poke(true.B)
            dut.io.cacheResp.valid.poke(true.B)
            dut.io.cacheResp.ready.expect(true.B)
            dut.io.ifetchPtwResp.valid.expect(false.B)
            dut.io.lsuResp.valid.expect(false.B)
            dut.clock.step()

            dut.io.maintPending.poke(false.B)
            dut.io.cacheResp.valid.poke(false.B)
            dut.io.respPending.expect(false.B)

            dut.io.lsuReq.valid.poke(true.B)
            dut.io.cacheReq.ready.poke(true.B)
            dut.io.lsuReq.ready.expect(true.B)
        }
    }
}
