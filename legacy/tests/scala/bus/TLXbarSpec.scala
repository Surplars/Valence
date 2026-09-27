package bus

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.{TLParams, TLPermissions, TLRAM, TLXbar, TLOpcode}

class TLXbarHarness(params: TLParams, supportsRelease: Seq[Boolean] = Seq(true)) extends Module {
    val io = IO(new Bundle {
        val master = Flipped(new soc.bus.tilelink.TLBundle(params))
    })

    val xbar = Module(new TLXbar(
        params,
        nMasters = 1,
        nSlaves = 1,
        addrMap = Seq((addr: UInt) => addr >= "h1000".U && addr < "h2000".U),
        supportsRelease = supportsRelease
    ))
    val ram = Module(new TLRAM(params, sizeBytes = 4096, base = 0x1000))

    xbar.io.masters(0) <> io.master
    xbar.io.slaves(0) <> ram.io.tl
}

class TLXbarSpec extends AnyFunSuite with ChiselSim {
    private val params = TLParams(addrWidth = 32, dataWidth = 64, sourceBits = 4, sinkBits = 1, sizeBits = 3)

    private def driveDefaults(dut: TLXbarHarness): Unit = {
        dut.io.master.a.valid.poke(false.B)
        dut.io.master.a.bits.opcode.poke(0.U)
        dut.io.master.a.bits.param.poke(0.U)
        dut.io.master.a.bits.size.poke(3.U)
        dut.io.master.a.bits.source.poke(0.U)
        dut.io.master.a.bits.address.poke(0.U)
        dut.io.master.a.bits.mask.poke(0.U)
        dut.io.master.a.bits.data.poke(0.U)
        dut.io.master.a.bits.corrupt.poke(false.B)
        dut.io.master.d.ready.poke(false.B)
        dut.io.master.b.ready.poke(true.B)
        dut.io.master.c.valid.poke(false.B)
        dut.io.master.c.bits.opcode.poke(0.U)
        dut.io.master.c.bits.param.poke(0.U)
        dut.io.master.c.bits.size.poke(3.U)
        dut.io.master.c.bits.source.poke(0.U)
        dut.io.master.c.bits.address.poke(0.U)
        dut.io.master.c.bits.data.poke(0.U)
        dut.io.master.c.bits.corrupt.poke(false.B)
        dut.io.master.e.valid.poke(false.B)
        dut.io.master.e.bits.sink.poke(0.U)
    }

    test("TLXbar returns denied responses and still routes mapped requests") {
        simulate(new TLXbarHarness(params)) { dut =>
            driveDefaults(dut)
            dut.io.master.d.ready.poke(true.B)

            dut.io.master.a.bits.opcode.poke(TLOpcode.Get)
            dut.io.master.a.bits.size.poke(3.U)
            dut.io.master.a.bits.source.poke(9.U)
            dut.io.master.a.bits.address.poke("h3000".U)
            dut.io.master.a.bits.mask.poke("hff".U)
            dut.io.master.a.valid.poke(true.B)
            dut.io.master.a.ready.expect(true.B)
            dut.clock.step()
            dut.io.master.a.valid.poke(false.B)

            dut.io.master.d.valid.expect(true.B)
            dut.io.master.d.bits.opcode.expect(TLOpcode.AccessAckData)
            dut.io.master.d.bits.source.expect(9.U)
            dut.io.master.d.bits.denied.expect(true.B)

            dut.io.master.a.bits.opcode.poke(TLOpcode.PutFullData)
            dut.io.master.a.bits.size.poke(3.U)
            dut.io.master.a.bits.source.poke(2.U)
            dut.io.master.a.bits.address.poke("h1000".U)
            dut.io.master.a.bits.mask.poke("hff".U)
            dut.io.master.a.bits.data.poke("h0123456789abcdef".U)
            dut.io.master.a.valid.poke(true.B)
            dut.io.master.a.ready.expect(true.B)
            dut.clock.step()
            dut.io.master.a.valid.poke(false.B)

            var sawWriteAck = false
            for (_ <- 0 until 8 if !sawWriteAck) {
                if (dut.io.master.d.valid.peek().litToBoolean) {
                    dut.io.master.d.bits.opcode.expect(TLOpcode.AccessAck)
                    dut.io.master.d.bits.source.expect(2.U)
                    dut.io.master.d.bits.denied.expect(false.B)
                    sawWriteAck = true
                }
                dut.clock.step()
            }
            assert(sawWriteAck, "mapped write did not receive an ACK")

            dut.io.master.a.bits.opcode.poke(TLOpcode.Get)
            dut.io.master.a.bits.size.poke(3.U)
            dut.io.master.a.bits.source.poke(3.U)
            dut.io.master.a.bits.address.poke("h1000".U)
            dut.io.master.a.bits.mask.poke("hff".U)
            dut.io.master.a.bits.data.poke(0.U)
            dut.io.master.a.valid.poke(true.B)
            dut.io.master.a.ready.expect(true.B)
            dut.clock.step()
            dut.io.master.a.valid.poke(false.B)

            var sawReadAck = false
            for (_ <- 0 until 8 if !sawReadAck) {
                if (dut.io.master.d.valid.peek().litToBoolean) {
                    dut.io.master.d.bits.opcode.expect(TLOpcode.AccessAckData)
                    dut.io.master.d.bits.source.expect(3.U)
                    dut.io.master.d.bits.denied.expect(false.B)
                    dut.io.master.d.bits.data.expect(BigInt("0123456789abcdef", 16))
                    sawReadAck = true
                }
                dut.clock.step()
            }
            assert(sawReadAck, "mapped read did not receive data")

            dut.io.master.a.bits.opcode.poke(TLOpcode.Get)
            dut.io.master.a.bits.size.poke(0.U)
            dut.io.master.a.bits.source.poke(4.U)
            dut.io.master.a.bits.address.poke("h1005".U)
            dut.io.master.a.bits.mask.poke("h20".U)
            dut.io.master.a.bits.data.poke(0.U)
            dut.io.master.a.valid.poke(true.B)
            dut.io.master.a.ready.expect(true.B)
            dut.clock.step()
            dut.io.master.a.valid.poke(false.B)

            var sawByteReadAck = false
            for (_ <- 0 until 8 if !sawByteReadAck) {
                if (dut.io.master.d.valid.peek().litToBoolean) {
                    dut.io.master.d.bits.opcode.expect(TLOpcode.AccessAckData)
                    dut.io.master.d.bits.source.expect(4.U)
                    dut.io.master.d.bits.denied.expect(false.B)
                    dut.io.master.d.bits.data.expect(BigInt("0123456789abcdef", 16))
                    sawByteReadAck = true
                }
                dut.clock.step()
            }
            assert(sawByteReadAck, "mapped byte read did not preserve beat lanes")
        }
    }

    test("TLXbar routes basic TL-C acquire requests to managers") {
        simulate(new TLXbarHarness(params)) { dut =>
            driveDefaults(dut)
            dut.io.master.d.ready.poke(true.B)

            dut.io.master.a.bits.opcode.poke(TLOpcode.AcquireBlock)
            dut.io.master.a.bits.param.poke(TLPermissions.nToT)
            dut.io.master.a.bits.size.poke(3.U)
            dut.io.master.a.bits.source.poke(1.U)
            dut.io.master.a.bits.address.poke("h1000".U)
            dut.io.master.a.bits.mask.poke("hff".U)
            dut.io.master.a.bits.data.poke(0.U)
            dut.io.master.a.valid.poke(true.B)
            dut.io.master.a.ready.expect(true.B)
            dut.clock.step()
            dut.io.master.a.valid.poke(false.B)

            var sawGrantData = false
            for (_ <- 0 until 8 if !sawGrantData) {
                if (dut.io.master.d.valid.peek().litToBoolean) {
                    dut.io.master.d.bits.opcode.expect(TLOpcode.GrantData)
                    dut.io.master.d.bits.param.expect(TLPermissions.nToT)
                    dut.io.master.d.bits.source.expect(1.U)
                    dut.io.master.d.bits.denied.expect(false.B)
                    sawGrantData = true
                }
                dut.clock.step()
            }
            assert(sawGrantData, "AcquireBlock did not receive GrantData")

            dut.io.master.a.bits.opcode.poke(TLOpcode.AcquirePerm)
            dut.io.master.a.bits.param.poke(TLPermissions.nToB)
            dut.io.master.a.bits.size.poke(3.U)
            dut.io.master.a.bits.source.poke(2.U)
            dut.io.master.a.bits.address.poke("h1008".U)
            dut.io.master.a.bits.mask.poke("hff".U)
            dut.io.master.a.valid.poke(true.B)
            dut.io.master.a.ready.expect(true.B)
            dut.clock.step()
            dut.io.master.a.valid.poke(false.B)

            var sawGrant = false
            for (_ <- 0 until 8 if !sawGrant) {
                if (dut.io.master.d.valid.peek().litToBoolean) {
                    dut.io.master.d.bits.opcode.expect(TLOpcode.Grant)
                    dut.io.master.d.bits.param.expect(TLPermissions.nToB)
                    dut.io.master.d.bits.source.expect(2.U)
                    dut.io.master.d.bits.denied.expect(false.B)
                    sawGrant = true
                }
                dut.clock.step()
            }
            assert(sawGrant, "AcquirePerm did not receive Grant")

            dut.io.master.a.bits.opcode.poke(TLOpcode.AcquireBlock)
            dut.io.master.a.bits.param.poke(TLPermissions.nToT)
            dut.io.master.a.bits.size.poke(3.U)
            dut.io.master.a.bits.source.poke(3.U)
            dut.io.master.a.bits.address.poke("h3000".U)
            dut.io.master.a.bits.mask.poke("hff".U)
            dut.io.master.a.valid.poke(true.B)
            dut.io.master.a.ready.expect(true.B)
            dut.clock.step()
            dut.io.master.a.valid.poke(false.B)

            var sawDeniedGrantData = false
            for (_ <- 0 until 8 if !sawDeniedGrantData) {
                if (dut.io.master.d.valid.peek().litToBoolean) {
                    dut.io.master.d.bits.opcode.expect(TLOpcode.GrantData)
                    dut.io.master.d.bits.param.expect(TLPermissions.nToT)
                    dut.io.master.d.bits.source.expect(3.U)
                    dut.io.master.d.bits.denied.expect(true.B)
                    sawDeniedGrantData = true
                }
                dut.clock.step()
            }
            assert(sawDeniedGrantData, "unmapped AcquireBlock did not receive denied GrantData")
        }
    }

    test("TLXbar routes TL-C release requests and returns ReleaseAck") {
        simulate(new TLXbarHarness(params)) { dut =>
            driveDefaults(dut)
            dut.io.master.d.ready.poke(true.B)

            dut.io.master.c.bits.opcode.poke(TLOpcode.ReleaseData)
            dut.io.master.c.bits.param.poke(TLPermissions.tToN)
            dut.io.master.c.bits.size.poke(3.U)
            dut.io.master.c.bits.source.poke(5.U)
            dut.io.master.c.bits.address.poke("h1010".U)
            dut.io.master.c.bits.data.poke("hfeedfacecafebeef".U)
            dut.io.master.c.bits.corrupt.poke(false.B)
            dut.io.master.c.valid.poke(true.B)
            dut.io.master.c.ready.expect(true.B)
            dut.clock.step()
            dut.io.master.c.valid.poke(false.B)

            var sawReleaseAck = false
            for (_ <- 0 until 8 if !sawReleaseAck) {
                if (dut.io.master.d.valid.peek().litToBoolean) {
                    dut.io.master.d.bits.opcode.expect(TLOpcode.ReleaseAck)
                    dut.io.master.d.bits.source.expect(5.U)
                    dut.io.master.d.bits.denied.expect(false.B)
                    sawReleaseAck = true
                }
                dut.clock.step()
            }
            assert(sawReleaseAck, "ReleaseData did not receive ReleaseAck")

            dut.io.master.a.bits.opcode.poke(TLOpcode.Get)
            dut.io.master.a.bits.size.poke(3.U)
            dut.io.master.a.bits.source.poke(6.U)
            dut.io.master.a.bits.address.poke("h1010".U)
            dut.io.master.a.bits.mask.poke("hff".U)
            dut.io.master.a.valid.poke(true.B)
            dut.io.master.a.ready.expect(true.B)
            dut.clock.step()
            dut.io.master.a.valid.poke(false.B)

            var sawReleasedData = false
            for (_ <- 0 until 8 if !sawReleasedData) {
                if (dut.io.master.d.valid.peek().litToBoolean) {
                    dut.io.master.d.bits.opcode.expect(TLOpcode.AccessAckData)
                    dut.io.master.d.bits.source.expect(6.U)
                    dut.io.master.d.bits.denied.expect(false.B)
                    dut.io.master.d.bits.data.expect(BigInt("feedfacecafebeef", 16))
                    sawReleasedData = true
                }
                dut.clock.step()
            }
            assert(sawReleasedData, "ReleaseData payload was not written through to RAM")

            dut.io.master.c.bits.opcode.poke(TLOpcode.Release)
            dut.io.master.c.bits.param.poke(TLPermissions.tToN)
            dut.io.master.c.bits.size.poke(3.U)
            dut.io.master.c.bits.source.poke(7.U)
            dut.io.master.c.bits.address.poke("h3000".U)
            dut.io.master.c.bits.data.poke(0.U)
            dut.io.master.c.valid.poke(true.B)
            dut.io.master.c.ready.expect(true.B)
            dut.clock.step()
            dut.io.master.c.valid.poke(false.B)

            var sawDeniedReleaseAck = false
            for (_ <- 0 until 8 if !sawDeniedReleaseAck) {
                if (dut.io.master.d.valid.peek().litToBoolean) {
                    dut.io.master.d.bits.opcode.expect(TLOpcode.ReleaseAck)
                    dut.io.master.d.bits.source.expect(7.U)
                    dut.io.master.d.bits.denied.expect(true.B)
                    sawDeniedReleaseAck = true
                }
                dut.clock.step()
            }
            assert(sawDeniedReleaseAck, "unmapped Release did not receive denied ReleaseAck")
        }
    }

    test("TLXbar denies release requests to managers without C-channel support") {
        simulate(new TLXbarHarness(params, supportsRelease = Seq(false))) { dut =>
            driveDefaults(dut)
            dut.io.master.d.ready.poke(true.B)

            dut.io.master.c.bits.opcode.poke(TLOpcode.Release)
            dut.io.master.c.bits.param.poke(TLPermissions.tToN)
            dut.io.master.c.bits.size.poke(3.U)
            dut.io.master.c.bits.source.poke(8.U)
            dut.io.master.c.bits.address.poke("h1000".U)
            dut.io.master.c.bits.data.poke(0.U)
            dut.io.master.c.valid.poke(true.B)
            dut.io.master.c.ready.expect(true.B)
            dut.clock.step()
            dut.io.master.c.valid.poke(false.B)

            var sawDeniedReleaseAck = false
            for (_ <- 0 until 8 if !sawDeniedReleaseAck) {
                if (dut.io.master.d.valid.peek().litToBoolean) {
                    dut.io.master.d.bits.opcode.expect(TLOpcode.ReleaseAck)
                    dut.io.master.d.bits.source.expect(8.U)
                    dut.io.master.d.bits.denied.expect(true.B)
                    sawDeniedReleaseAck = true
                }
                dut.clock.step()
            }
            assert(sawDeniedReleaseAck, "unsupported C-channel manager did not receive denied ReleaseAck")
        }
    }
}
