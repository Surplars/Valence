package memory

import chisel3._
import chisel3.util._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.{TLCoherenceHub, TLParams, TLPermissions, TLRAM, TLOpcode}
import soc.device.TLError
import soc.memory.cache.{CacheCmd, L1Cache, UncachedTileLinkBridge}

class CacheMappedRamHarness(params: TLParams) extends Module {
    val io = IO(new Bundle {
        val req  = Flipped(Decoupled(new soc.memory.CacheReq(params.addrWidth, params.dataWidth)))
        val resp = Decoupled(new soc.memory.CacheResp(params.dataWidth))
    })

    val cache = Module(new L1Cache(params, nSets = 4, useTLCoherence = false))
    val xbar = Module(new soc.bus.tilelink.TLXbar(
        params,
        nMasters = 1,
        nSlaves = 1,
        addrMap = Seq(addr => addr < 0x1000.U)
    ))
    val ram = Module(new TLRAM(params, sizeBytes = 4096))

    cache.io.cpu.req <> io.req
    io.resp <> cache.io.cpu.resp
    cache.io.invalidate.valid := false.B
    cache.io.invalidate.bits := false.B
    xbar.io.masters(0) <> cache.io.bus
    ram.io.tl <> xbar.io.slaves(0)
}

class CacheDeniedHarness(params: TLParams) extends Module {
    val io = IO(new Bundle {
        val req  = Flipped(Decoupled(new soc.memory.CacheReq(params.addrWidth, params.dataWidth)))
        val resp = Decoupled(new soc.memory.CacheResp(params.dataWidth))
    })

    val cache = Module(new L1Cache(params, nSets = 4, useTLCoherence = false))
    val error = Module(new TLError(params))

    cache.io.cpu.req <> io.req
    io.resp <> cache.io.cpu.resp
    cache.io.invalidate.valid := false.B
    cache.io.invalidate.bits := false.B
    error.io.tl <> cache.io.bus
}

class UncachedDeniedHarness(params: TLParams) extends Module {
    val io = IO(new Bundle {
        val req  = Flipped(Decoupled(new soc.memory.CacheReq(params.addrWidth, params.dataWidth)))
        val resp = Decoupled(new soc.memory.CacheResp(params.dataWidth))
    })

    val bridge = Module(new UncachedTileLinkBridge(params))
    val error = Module(new TLError(params))

    bridge.io.cpu.req <> io.req
    io.resp <> bridge.io.cpu.resp
    bridge.io.invalidate.valid := false.B
    bridge.io.invalidate.bits := false.B
    error.io.tl <> bridge.io.bus
}

class CacheRamHarness(params: TLParams, nSets: Int = 4) extends Module {
    val io = IO(new Bundle {
        val req  = Flipped(Decoupled(new soc.memory.CacheReq(params.addrWidth, params.dataWidth)))
        val resp = Decoupled(new soc.memory.CacheResp(params.dataWidth))
        val invalidate = Flipped(Decoupled(Bool()))
        val probe = Flipped(Decoupled(new soc.bus.tilelink.TLBundleB(params)))
        val probeAck = Decoupled(new soc.bus.tilelink.TLBundleC(params))
        val seenAcquire = Output(Bool())
        val seenRelease = Output(Bool())
    })

    val cache = Module(new L1Cache(params, nSets = nSets))
    val ram = Module(new TLRAM(params, sizeBytes = 4096))

    val seenAcquire = RegInit(false.B)
    val seenRelease = RegInit(false.B)
    when(cache.io.bus.a.fire && cache.io.bus.a.bits.opcode === soc.bus.tilelink.TLOpcode.AcquireBlock) {
        seenAcquire := true.B
    }
    when(cache.io.bus.c.fire && cache.io.bus.c.bits.opcode === soc.bus.tilelink.TLOpcode.ReleaseData) {
        seenRelease := true.B
    }

    cache.io.cpu.req <> io.req
    io.resp <> cache.io.cpu.resp
    cache.io.invalidate <> io.invalidate
    cache.io.bus.b.valid := io.probe.valid
    cache.io.bus.b.bits := io.probe.bits
    io.probe.ready := cache.io.bus.b.ready
    ram.io.tl.a <> cache.io.bus.a
    cache.io.bus.d <> ram.io.tl.d
    val cacheCIsProbeAck = cache.io.bus.c.bits.opcode === TLOpcode.ProbeAck ||
        cache.io.bus.c.bits.opcode === TLOpcode.ProbeAckData
    io.probeAck.valid := cache.io.bus.c.valid && cacheCIsProbeAck
    io.probeAck.bits := cache.io.bus.c.bits
    ram.io.tl.c.valid := cache.io.bus.c.valid && !cacheCIsProbeAck
    ram.io.tl.c.bits := cache.io.bus.c.bits
    cache.io.bus.c.ready := Mux(cacheCIsProbeAck, io.probeAck.ready, ram.io.tl.c.ready)
    cache.io.bus.e.ready := true.B
    ram.io.tl.b.ready := true.B
    ram.io.tl.e.valid := false.B
    ram.io.tl.e.bits := 0.U.asTypeOf(ram.io.tl.e.bits)
    io.seenAcquire := seenAcquire
    io.seenRelease := seenRelease
}

class DualCacheCoherenceHarness(params: TLParams) extends Module {
    val io = IO(new Bundle {
        val req0 = Flipped(Decoupled(new soc.memory.CacheReq(params.addrWidth, params.dataWidth)))
        val resp0 = Decoupled(new soc.memory.CacheResp(params.dataWidth))
        val req1 = Flipped(Decoupled(new soc.memory.CacheReq(params.addrWidth, params.dataWidth)))
        val resp1 = Decoupled(new soc.memory.CacheResp(params.dataWidth))
        val seenProbe0 = Output(Bool())
        val seenProbe1 = Output(Bool())
        val seenProbeAck0 = Output(Bool())
        val seenProbeAck1 = Output(Bool())
        val seenReleaseToMemory = Output(Bool())
        val seenReleaseAckFromMemory = Output(Bool())
        val seenAcquire0 = Output(Bool())
        val seenAcquire1 = Output(Bool())
        val seenGrant1 = Output(Bool())
    })

    private val hubParams = params.copy(sourceBits = params.sourceBits + 1)
    val cache0 = Module(new L1Cache(params, nSets = 4))
    val cache1 = Module(new L1Cache(params, nSets = 4))
    val hub = Module(new TLCoherenceHub(params, nClients = 2, nEntries = 4))
    val ram = Module(new TLRAM(hubParams, sizeBytes = 4096))

    val seenProbe0 = RegInit(false.B)
    val seenProbe1 = RegInit(false.B)
    val seenProbeAck0 = RegInit(false.B)
    val seenProbeAck1 = RegInit(false.B)
    val seenReleaseToMemory = RegInit(false.B)
    val seenReleaseAckFromMemory = RegInit(false.B)
    val seenAcquire0 = RegInit(false.B)
    val seenAcquire1 = RegInit(false.B)
    val seenGrant1 = RegInit(false.B)
    when(cache0.io.bus.a.fire && cache0.io.bus.a.bits.opcode === TLOpcode.AcquireBlock) {
        seenAcquire0 := true.B
    }
    when(cache1.io.bus.a.fire && cache1.io.bus.a.bits.opcode === TLOpcode.AcquireBlock) {
        seenAcquire1 := true.B
    }
    when(cache0.io.bus.b.fire) {
        seenProbe0 := true.B
    }
    when(cache1.io.bus.b.fire) {
        seenProbe1 := true.B
    }
    when(cache0.io.bus.c.fire && cache0.io.bus.c.bits.opcode === TLOpcode.ProbeAckData) {
        seenProbeAck0 := true.B
    }
    when(cache1.io.bus.c.fire && cache1.io.bus.c.bits.opcode === TLOpcode.ProbeAck) {
        seenProbeAck1 := true.B
    }
    when(hub.io.manager.c.fire && hub.io.manager.c.bits.opcode === TLOpcode.ReleaseData) {
        seenReleaseToMemory := true.B
    }
    when(hub.io.manager.d.fire && hub.io.manager.d.bits.opcode === TLOpcode.ReleaseAck) {
        seenReleaseAckFromMemory := true.B
    }
    when(cache1.io.bus.d.fire && cache1.io.bus.d.bits.opcode === TLOpcode.GrantData) {
        seenGrant1 := true.B
    }

    cache0.io.cpu.req <> io.req0
    io.resp0 <> cache0.io.cpu.resp
    cache1.io.cpu.req <> io.req1
    io.resp1 <> cache1.io.cpu.resp
    cache0.io.invalidate.valid := false.B
    cache0.io.invalidate.bits := false.B
    cache1.io.invalidate.valid := false.B
    cache1.io.invalidate.bits := false.B

    hub.io.clients(0) <> cache0.io.bus
    hub.io.clients(1) <> cache1.io.bus
    ram.io.tl <> hub.io.manager

    io.seenProbe0 := seenProbe0
    io.seenProbe1 := seenProbe1
    io.seenProbeAck0 := seenProbeAck0
    io.seenProbeAck1 := seenProbeAck1
    io.seenReleaseToMemory := seenReleaseToMemory
    io.seenReleaseAckFromMemory := seenReleaseAckFromMemory
    io.seenAcquire0 := seenAcquire0
    io.seenAcquire1 := seenAcquire1
    io.seenGrant1 := seenGrant1
}

class L1CacheSpec extends AnyFunSuite with ChiselSim {
    private val params = TLParams(addrWidth = 32, dataWidth = 64, sourceBits = 4, sinkBits = 1, sizeBits = 3)

    private def init(dut: CacheRamHarness): Unit = {
        dut.io.req.valid.poke(false.B)
        dut.io.invalidate.valid.poke(false.B)
        dut.io.invalidate.bits.poke(false.B)
        dut.io.probe.valid.poke(false.B)
        dut.io.probe.bits.opcode.poke(TLOpcode.ProbeBlock)
        dut.io.probe.bits.param.poke(TLPermissions.toN)
        dut.io.probe.bits.size.poke(3.U)
        dut.io.probe.bits.source.poke(0.U)
        dut.io.probe.bits.address.poke(0.U)
        dut.io.probe.bits.mask.poke("hff".U)
        dut.io.probe.bits.data.poke(0.U)
        dut.io.probe.bits.corrupt.poke(false.B)
        dut.io.probeAck.ready.poke(true.B)
        dut.io.resp.ready.poke(true.B)
    }

    private def pokeReq(
        dut: CacheRamHarness,
        addr: BigInt,
        cmd: CacheCmd.Type,
        data: BigInt = 0,
        mask: BigInt = 0xff,
        fence: Boolean = false,
        fencei: Boolean = false
    ): Unit = {
        dut.io.req.bits.addr.poke(addr.U)
        dut.io.req.bits.vaddr.poke(addr.U)
        dut.io.req.bits.cmd.poke(cmd)
        dut.io.req.bits.wdata.poke(data.U)
        dut.io.req.bits.mask.poke(mask.U)
        dut.io.req.bits.size.poke(3.U)
        dut.io.req.bits.signed.poke(false.B)
        dut.io.req.bits.fence.poke(fence.B)
        dut.io.req.bits.fencei.poke(fencei.B)
        dut.io.req.bits.atomic.poke(false.B)
        dut.io.req.bits.cacheable.poke(true.B)
        dut.io.req.bits.device.poke(false.B)
    }

    private def pokeCacheReq(
        req: DecoupledIO[soc.memory.CacheReq],
        addr: BigInt,
        cmd: CacheCmd.Type,
        data: BigInt = 0,
        mask: BigInt = 0xff
    ): Unit = {
        req.bits.addr.poke(addr.U)
        req.bits.vaddr.poke(addr.U)
        req.bits.cmd.poke(cmd)
        req.bits.wdata.poke(data.U)
        req.bits.mask.poke(mask.U)
        req.bits.size.poke(3.U)
        req.bits.signed.poke(false.B)
        req.bits.fence.poke(false.B)
        req.bits.fencei.poke(false.B)
        req.bits.atomic.poke(false.B)
        req.bits.cacheable.poke(true.B)
        req.bits.device.poke(false.B)
    }

    private def issueCacheReq(req: DecoupledIO[soc.memory.CacheReq], clock: Clock): Unit = {
        req.valid.poke(true.B)
        req.ready.expect(true.B)
        clock.step()
        req.valid.poke(false.B)
    }

    private def waitCacheResp(
        resp: DecoupledIO[soc.memory.CacheResp],
        clock: Clock,
        maxCycles: Int = 60,
        label: String = "cache"
    ): BigInt = {
        var sawResp = false
        var data = BigInt(0)
        for (_ <- 0 until maxCycles if !sawResp) {
            if (resp.valid.peek().litToBoolean) {
                resp.bits.err.expect(false.B)
                data = resp.bits.rdata.peek().litValue
                sawResp = true
            }
            clock.step()
        }
        assert(sawResp, s"$label response was not observed")
        data
    }

    private def waitUntil(clock: Clock, maxCycles: Int, label: String)(cond: => Boolean): Unit = {
        var done = false
        for (_ <- 0 until maxCycles if !done) {
            done = cond
            if (!done) {
                clock.step()
            }
        }
        assert(done, s"$label was not observed")
    }

    private def issueReq(dut: CacheRamHarness): Unit = {
        dut.io.req.valid.poke(true.B)
        dut.io.req.ready.expect(true.B)
        dut.clock.step()
        dut.io.req.valid.poke(false.B)
    }

    private def waitResp(dut: CacheRamHarness, maxCycles: Int = 30): BigInt = {
        var sawResp = false
        var data = BigInt(0)
        for (_ <- 0 until maxCycles if !sawResp) {
            if (dut.io.resp.valid.peek().litToBoolean) {
                dut.io.resp.bits.err.expect(false.B)
                data = dut.io.resp.bits.rdata.peek().litValue
                sawResp = true
            }
            dut.clock.step()
        }
        assert(sawResp, "cache response was not observed")
        data
    }

    private def issueInvalidate(dut: CacheRamHarness, maxCycles: Int = 80): Unit = {
        dut.io.invalidate.valid.poke(true.B)
        dut.io.invalidate.bits.poke(false.B)
        dut.io.invalidate.ready.expect(true.B)
        dut.clock.step()
        dut.io.invalidate.valid.poke(false.B)

        var sawResp = false
        for (_ <- 0 until maxCycles if !sawResp) {
            if (dut.io.resp.valid.peek().litToBoolean) {
                dut.io.resp.bits.err.expect(false.B)
                sawResp = true
            }
            dut.clock.step()
        }
        assert(sawResp, "cache invalidate did not complete")
    }

    private def issueProbe(dut: CacheRamHarness, addr: BigInt, expectData: Boolean, source: Int = 9): BigInt = {
        dut.io.probe.bits.opcode.poke(TLOpcode.ProbeBlock)
        dut.io.probe.bits.param.poke(TLPermissions.toN)
        dut.io.probe.bits.size.poke(3.U)
        dut.io.probe.bits.source.poke(source.U)
        dut.io.probe.bits.address.poke(addr.U)
        dut.io.probe.bits.mask.poke("hff".U)
        dut.io.probe.bits.data.poke(0.U)
        dut.io.probe.bits.corrupt.poke(false.B)
        dut.io.probe.valid.poke(true.B)
        dut.io.probe.ready.expect(true.B)
        dut.clock.step()
        dut.io.probe.valid.poke(false.B)

        var sawAck = false
        var data = BigInt(0)
        for (_ <- 0 until 12 if !sawAck) {
            if (dut.io.probeAck.valid.peek().litToBoolean) {
                dut.io.probeAck.bits.opcode.expect(if (expectData) TLOpcode.ProbeAckData else TLOpcode.ProbeAck)
                dut.io.probeAck.bits.param.expect(TLPermissions.toN)
                dut.io.probeAck.bits.source.expect(source.U)
                data = dut.io.probeAck.bits.data.peek().litValue
                sawAck = true
            }
            dut.clock.step()
        }
        assert(sawAck, "cache probe did not produce ProbeAck")
        data
    }

    test("Cache hit response remains stable under CPU backpressure") {
        simulate(new CacheRamHarness(params)) { dut =>
            dut.io.req.valid.poke(false.B)
            dut.io.resp.ready.poke(true.B)

            pokeReq(dut, addr = 0x80, cmd = CacheCmd.Write, data = BigInt("1122334455667788", 16))
            dut.io.req.valid.poke(true.B)
            dut.io.req.ready.expect(true.B)
            dut.clock.step()
            dut.io.req.valid.poke(false.B)

            var writeDone = false
            for (_ <- 0 until 20 if !writeDone) {
                if (dut.io.resp.valid.peek().litToBoolean) {
                    dut.io.resp.bits.err.expect(false.B)
                    writeDone = true
                }
                dut.clock.step()
            }
            assert(writeDone, "cache write miss did not complete")
            dut.io.seenAcquire.expect(true.B)

            pokeReq(dut, addr = 0x80, cmd = CacheCmd.Read)
            dut.io.resp.ready.poke(false.B)
            dut.io.req.valid.poke(true.B)
            dut.io.req.ready.expect(true.B)
            dut.clock.step()
            dut.io.req.valid.poke(false.B)

            var sawHeldResp = false
            for (_ <- 0 until 10 if !sawHeldResp) {
                if (dut.io.resp.valid.peek().litToBoolean) {
                    dut.io.resp.bits.err.expect(false.B)
                    dut.io.resp.bits.rdata.expect("h1122334455667788".U)
                    dut.clock.step(3)
                    dut.io.resp.valid.expect(true.B)
                    dut.io.resp.bits.rdata.expect("h1122334455667788".U)
                    sawHeldResp = true
                } else {
                    dut.clock.step()
                }
            }
            assert(sawHeldResp, "cache hit response was not observed")

            dut.io.resp.ready.poke(true.B)
            dut.clock.step()
        }
    }

    test("Cache invalidate forces a later refill") {
        simulate(new CacheRamHarness(params)) { dut =>
            init(dut)

            pokeReq(dut, addr = 0x100, cmd = CacheCmd.Write, data = BigInt("aaaabbbbccccdddd", 16))
            issueReq(dut)
            waitResp(dut)

            pokeReq(dut, addr = 0x100, cmd = CacheCmd.Read)
            issueReq(dut)
            assert(waitResp(dut) == BigInt("aaaabbbbccccdddd", 16))

            pokeReq(dut, addr = 0x900, cmd = CacheCmd.Write, data = BigInt("1111222233334444", 16))
            issueReq(dut)
            waitResp(dut)

            issueInvalidate(dut)
            dut.io.seenRelease.expect(true.B)

            pokeReq(dut, addr = 0x100, cmd = CacheCmd.Read)
            issueReq(dut)
            assert(waitResp(dut) == BigInt("aaaabbbbccccdddd", 16))
        }
    }

    test("Cache invalidate writes back dirty lines before dropping them") {
        simulate(new CacheRamHarness(params)) { dut =>
            init(dut)

            pokeReq(dut, addr = 0x80, cmd = CacheCmd.Write, data = BigInt("cafebabedeadbeef", 16))
            issueReq(dut)
            waitResp(dut, maxCycles = 40)

            issueInvalidate(dut)
            dut.io.seenRelease.expect(true.B)

            pokeReq(dut, addr = 0x80, cmd = CacheCmd.Read)
            issueReq(dut)
            assert(waitResp(dut, maxCycles = 40) == BigInt("cafebabedeadbeef", 16))
        }
    }

    test("Cache drop-only invalidate completes without scanning every set") {
        simulate(new CacheRamHarness(params, nSets = 512)) { dut =>
            init(dut)

            dut.io.invalidate.valid.poke(true.B)
            dut.io.invalidate.bits.poke(true.B)
            dut.io.invalidate.ready.expect(true.B)
            dut.clock.step()
            dut.io.invalidate.valid.poke(false.B)

            waitResp(dut, maxCycles = 16)
        }
    }

    test("Cache CPU fence request flushes dirty lines") {
        simulate(new CacheRamHarness(params)) { dut =>
            init(dut)

            pokeReq(dut, addr = 0x1c0, cmd = CacheCmd.Write, data = BigInt("0102030405060708", 16))
            issueReq(dut)
            waitResp(dut, maxCycles = 40)

            // The core sends fence/fence.i through the CPU request side. The
            // cache uses the same maintenance FSM as the explicit invalidate port.
            pokeReq(dut, addr = 0x0, cmd = CacheCmd.Read, fence = true)
            issueReq(dut)
            waitResp(dut, maxCycles = 80)
            dut.io.seenRelease.expect(true.B)

            pokeReq(dut, addr = 0x1c0, cmd = CacheCmd.Read)
            issueReq(dut)
            assert(waitResp(dut, maxCycles = 40) == BigInt("0102030405060708", 16))
        }
    }

    test("Cache write hit preserves unmasked byte lanes") {
        simulate(new CacheRamHarness(params)) { dut =>
            init(dut)

            pokeReq(dut, addr = 0x180, cmd = CacheCmd.Write, data = BigInt("1122334455667788", 16))
            issueReq(dut)
            waitResp(dut, maxCycles = 40)

            pokeReq(dut, addr = 0x180, cmd = CacheCmd.Write, data = BigInt("0000000000aa0000", 16), mask = 0x04)
            issueReq(dut)
            waitResp(dut, maxCycles = 20)

            pokeReq(dut, addr = 0x180, cmd = CacheCmd.Read)
            issueReq(dut)
            assert(waitResp(dut, maxCycles = 20) == BigInt("1122334455aa7788", 16))
        }
    }

    test("Cache read hit responds in compare cycle") {
        simulate(new CacheRamHarness(params)) { dut =>
            init(dut)

            pokeReq(dut, addr = 0x188, cmd = CacheCmd.Write, data = BigInt("feedfacecafebeef", 16))
            issueReq(dut)
            waitResp(dut, maxCycles = 40)

            pokeReq(dut, addr = 0x188, cmd = CacheCmd.Read)
            issueReq(dut)
            dut.io.resp.valid.expect(true.B)
            dut.io.resp.bits.rdata.expect("hfeedfacecafebeef".U)
            dut.clock.step()
            dut.io.resp.valid.expect(false.B)
        }
    }

    test("Cache hit responses clear stale denied error state") {
        simulate(new CacheMappedRamHarness(params)) { dut =>
            dut.io.req.valid.poke(false.B)
            dut.io.resp.ready.poke(true.B)

            pokeCacheReq(dut.io.req, addr = 0x188, cmd = CacheCmd.Write, data = BigInt("feedfacecafebeef", 16))
            issueCacheReq(dut.io.req, dut.clock)
            waitCacheResp(dut.io.resp, dut.clock, maxCycles = 40, label = "initial cache fill")

            pokeCacheReq(dut.io.req, addr = 0x188, cmd = CacheCmd.Read)
            issueCacheReq(dut.io.req, dut.clock)
            waitCacheResp(dut.io.resp, dut.clock, maxCycles = 8, label = "initial hit-buffer fill")

            pokeCacheReq(dut.io.req, addr = 0x2000, cmd = CacheCmd.Read)
            issueCacheReq(dut.io.req, dut.clock)

            var sawDenied = false
            for (_ <- 0 until 30 if !sawDenied) {
                if (dut.io.resp.valid.peek().litToBoolean) {
                    dut.io.resp.bits.err.expect(true.B)
                    sawDenied = true
                }
                dut.clock.step()
            }
            assert(sawDenied, "cache denied miss response was not observed")

            pokeCacheReq(dut.io.req, addr = 0x188, cmd = CacheCmd.Read)
            dut.io.req.valid.poke(true.B)
            dut.io.req.ready.expect(true.B)
            dut.io.resp.valid.expect(true.B)
            dut.io.resp.bits.err.expect(false.B)
            dut.io.resp.bits.rdata.expect("hfeedfacecafebeef".U)
            dut.io.req.valid.poke(false.B)
            dut.clock.step()
        }
    }

    test("Cache read hit buffer survives unrelated writes and tracks same-line writes") {
        simulate(new CacheRamHarness(params)) { dut =>
            init(dut)

            pokeReq(dut, addr = 0x100, cmd = CacheCmd.Write, data = BigInt("0102030405060708", 16))
            issueReq(dut)
            waitResp(dut, maxCycles = 40)

            pokeReq(dut, addr = 0x100, cmd = CacheCmd.Read)
            issueReq(dut)
            assert(waitResp(dut, maxCycles = 20) == BigInt("0102030405060708", 16))

            pokeReq(dut, addr = 0x108, cmd = CacheCmd.Write, data = BigInt("1112131415161718", 16))
            issueReq(dut)
            waitResp(dut, maxCycles = 40)

            pokeReq(dut, addr = 0x100, cmd = CacheCmd.Read)
            dut.io.req.valid.poke(true.B)
            dut.io.req.ready.expect(true.B)
            dut.io.resp.valid.expect(true.B)
            dut.io.resp.bits.rdata.expect("h0102030405060708".U)
            dut.io.req.valid.poke(false.B)
            dut.clock.step()
            dut.io.resp.valid.expect(false.B)

            pokeReq(dut, addr = 0x100, cmd = CacheCmd.Write, data = BigInt("00000000aa000000", 16), mask = 0x08)
            issueReq(dut)
            waitResp(dut, maxCycles = 20)

            pokeReq(dut, addr = 0x100, cmd = CacheCmd.Read)
            dut.io.req.valid.poke(true.B)
            dut.io.req.ready.expect(true.B)
            dut.io.resp.valid.expect(true.B)
            dut.io.resp.bits.rdata.expect("h01020304aa060708".U)
            dut.io.req.valid.poke(false.B)
            dut.clock.step()
        }
    }

    test("Cache responds to TL-C probes and invalidates matching lines") {
        simulate(new CacheRamHarness(params)) { dut =>
            init(dut)

            pokeReq(dut, addr = 0x200, cmd = CacheCmd.Write, data = BigInt("123456789abcdef0", 16))
            issueReq(dut)
            waitResp(dut, maxCycles = 40)

            val dirtyProbeData = issueProbe(dut, addr = 0x200, expectData = true)
            assert(dirtyProbeData == BigInt("123456789abcdef0", 16))

            pokeReq(dut, addr = 0x300, cmd = CacheCmd.Write, data = BigInt("0fedcba987654321", 16))
            issueReq(dut)
            waitResp(dut, maxCycles = 40)
            issueInvalidate(dut)

            pokeReq(dut, addr = 0x300, cmd = CacheCmd.Read)
            issueReq(dut)
            assert(waitResp(dut, maxCycles = 40) == BigInt("0fedcba987654321", 16))
            dut.io.seenAcquire.expect(true.B)

            val cleanProbeData = issueProbe(dut, addr = 0x300, expectData = false, source = 10)
            assert(cleanProbeData == 0)

            val missProbeData = issueProbe(dut, addr = 0x280, expectData = false, source = 11)
            assert(missProbeData == 0)
        }
    }

    test("Two L1 caches transfer a dirty line through TLCoherenceHub") {
        simulate(new DualCacheCoherenceHarness(params)) { dut =>
            dut.io.req0.valid.poke(false.B)
            dut.io.req1.valid.poke(false.B)
            dut.io.resp0.ready.poke(true.B)
            dut.io.resp1.ready.poke(true.B)

            pokeCacheReq(dut.io.req0, addr = 0x100, cmd = CacheCmd.Write, data = BigInt("deadbeefcafef00d", 16))
            issueCacheReq(dut.io.req0, dut.clock)
            waitCacheResp(dut.io.resp0, dut.clock, maxCycles = 80, label = "cache0 write miss")
            dut.io.seenAcquire0.expect(true.B)

            pokeCacheReq(dut.io.req1, addr = 0x100, cmd = CacheCmd.Read)
            issueCacheReq(dut.io.req1, dut.clock)
            waitUntil(dut.clock, maxCycles = 20, label = "AcquireBlock from cache1") {
                dut.io.seenAcquire1.peek().litToBoolean
            }
            waitUntil(dut.clock, maxCycles = 20, label = "probe to cache0") {
                dut.io.seenProbe0.peek().litToBoolean
            }
            waitUntil(dut.clock, maxCycles = 20, label = "ProbeAckData from cache0") {
                dut.io.seenProbeAck0.peek().litToBoolean
            }
            waitUntil(dut.clock, maxCycles = 20, label = "ReleaseData to memory") {
                dut.io.seenReleaseToMemory.peek().litToBoolean
            }
            waitUntil(dut.clock, maxCycles = 20, label = "ReleaseAck from memory") {
                dut.io.seenReleaseAckFromMemory.peek().litToBoolean
            }
            waitUntil(dut.clock, maxCycles = 20, label = "GrantData to cache1") {
                dut.io.seenGrant1.peek().litToBoolean
            }
            assert(waitCacheResp(dut.io.resp1, dut.clock, maxCycles = 20, label = "cache1 read transfer") == BigInt("deadbeefcafef00d", 16))

            pokeCacheReq(dut.io.req0, addr = 0x100, cmd = CacheCmd.Read)
            issueCacheReq(dut.io.req0, dut.clock)
            assert(waitCacheResp(dut.io.resp0, dut.clock, maxCycles = 100, label = "cache0 read reacquire") == BigInt("deadbeefcafef00d", 16))
            dut.io.seenProbe1.expect(true.B)
            dut.io.seenProbeAck1.expect(true.B)
        }
    }

    test("Cache bridges report denied responses") {
        simulate(new CacheDeniedHarness(params)) { dut =>
            dut.io.req.valid.poke(false.B)
            dut.io.req.bits.addr.poke(0.U)
            dut.io.req.bits.vaddr.poke(0.U)
            dut.io.req.bits.cmd.poke(CacheCmd.Read)
            dut.io.req.bits.wdata.poke(0.U)
            dut.io.req.bits.mask.poke("hff".U)
            dut.io.req.bits.size.poke(3.U)
            dut.io.req.bits.signed.poke(false.B)
            dut.io.req.bits.fence.poke(false.B)
            dut.io.req.bits.fencei.poke(false.B)
            dut.io.req.bits.atomic.poke(false.B)
            dut.io.req.bits.cacheable.poke(true.B)
            dut.io.req.bits.device.poke(false.B)
            dut.io.resp.ready.poke(true.B)

            dut.io.req.bits.addr.poke("h1000".U)
            dut.io.req.bits.vaddr.poke("h1000".U)
            dut.io.req.valid.poke(true.B)
            dut.io.req.ready.expect(true.B)
            dut.clock.step()
            dut.io.req.valid.poke(false.B)

            var sawResp = false
            for (_ <- 0 until 20 if !sawResp) {
                if (dut.io.resp.valid.peek().litToBoolean) {
                    dut.io.resp.bits.err.expect(true.B)
                    sawResp = true
                }
                dut.clock.step()
            }
            assert(sawResp, "cache did not produce a response for denied refill")
        }

        simulate(new UncachedDeniedHarness(params)) { dut =>
            dut.io.req.valid.poke(false.B)
            dut.io.req.bits.addr.poke("h3000".U)
            dut.io.req.bits.vaddr.poke("h3000".U)
            dut.io.req.bits.cmd.poke(CacheCmd.Read)
            dut.io.req.bits.wdata.poke(0.U)
            dut.io.req.bits.mask.poke("hff".U)
            dut.io.req.bits.size.poke(3.U)
            dut.io.req.bits.signed.poke(false.B)
            dut.io.req.bits.fence.poke(false.B)
            dut.io.req.bits.fencei.poke(false.B)
            dut.io.req.bits.atomic.poke(false.B)
            dut.io.req.bits.cacheable.poke(true.B)
            dut.io.req.bits.device.poke(false.B)
            dut.io.resp.ready.poke(true.B)

            dut.io.req.valid.poke(true.B)
            dut.io.req.ready.expect(true.B)
            dut.clock.step()
            dut.io.req.valid.poke(false.B)

            var sawResp = false
            for (_ <- 0 until 8 if !sawResp) {
                if (dut.io.resp.valid.peek().litToBoolean) {
                    dut.io.resp.bits.err.expect(true.B)
                    sawResp = true
                }
                dut.clock.step()
            }
            assert(sawResp, "uncached bridge did not produce a response")
        }
    }
}
