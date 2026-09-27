package device

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import soc.bus.tilelink._

trait TileLinkDeviceTestUtils { this: ChiselSim =>
    protected val deviceParams: TLParams =
        TLParams(addrWidth = 32, dataWidth = 64, sourceBits = 4, sinkBits = 1, sizeBits = 3)

    protected def initTlSlave(tl: TLBundle, size: Int = 3): Unit = {
        tl.a.valid.poke(false.B)
        tl.a.bits.opcode.poke(0.U)
        tl.a.bits.param.poke(0.U)
        tl.a.bits.size.poke(size.U)
        tl.a.bits.source.poke(0.U)
        tl.a.bits.address.poke(0.U)
        tl.a.bits.mask.poke(0.U)
        tl.a.bits.data.poke(0.U)
        tl.a.bits.corrupt.poke(false.B)
        tl.d.ready.poke(false.B)
        tl.b.ready.poke(true.B)
        tl.c.valid.poke(false.B)
        tl.c.bits.opcode.poke(0.U)
        tl.c.bits.param.poke(0.U)
        tl.c.bits.size.poke(size.U)
        tl.c.bits.source.poke(0.U)
        tl.c.bits.address.poke(0.U)
        tl.c.bits.data.poke(0.U)
        tl.c.bits.corrupt.poke(false.B)
        tl.e.valid.poke(false.B)
        tl.e.bits.sink.poke(0.U)
    }

    protected def writeTl(
        tl: TLBundle,
        clock: Clock,
        address: BigInt,
        data: BigInt,
        mask: BigInt,
        size: Int = 3,
        source: Int = 3,
        opcode: UInt = TLOpcode.PutPartialData,
        denied: Boolean = false
    ): Unit = {
        tl.d.ready.poke(true.B)
        tl.a.bits.opcode.poke(opcode)
        tl.a.bits.param.poke(0.U)
        tl.a.bits.size.poke(size.U)
        tl.a.bits.source.poke(source.U)
        tl.a.bits.address.poke(address.U)
        tl.a.bits.mask.poke(mask.U)
        tl.a.bits.data.poke(data.U)
        tl.a.bits.corrupt.poke(false.B)
        tl.a.valid.poke(true.B)
        tl.a.ready.expect(true.B)
        clock.step()
        tl.a.valid.poke(false.B)
        tl.d.valid.expect(true.B)
        tl.d.bits.opcode.expect(TLOpcode.AccessAck)
        tl.d.bits.source.expect(source.U)
        tl.d.bits.denied.expect(denied.B)
        clock.step()
    }

    protected def readTl(
        tl: TLBundle,
        clock: Clock,
        address: BigInt,
        mask: BigInt = 0xff,
        size: Int = 3,
        source: Int = 5,
        denied: Boolean = false
    ): BigInt = {
        tl.d.ready.poke(true.B)
        tl.a.bits.opcode.poke(TLOpcode.Get)
        tl.a.bits.param.poke(0.U)
        tl.a.bits.size.poke(size.U)
        tl.a.bits.source.poke(source.U)
        tl.a.bits.address.poke(address.U)
        tl.a.bits.mask.poke(mask.U)
        tl.a.bits.data.poke(0.U)
        tl.a.bits.corrupt.poke(false.B)
        tl.a.valid.poke(true.B)
        tl.a.ready.expect(true.B)
        clock.step()
        tl.a.valid.poke(false.B)
        tl.d.valid.expect(true.B)
        tl.d.bits.opcode.expect(TLOpcode.AccessAckData)
        tl.d.bits.source.expect(source.U)
        tl.d.bits.denied.expect(denied.B)
        val data = tl.d.bits.data.peek().litValue
        clock.step()
        data
    }

    protected def acquireBlockTl(
        tl: TLBundle,
        clock: Clock,
        address: BigInt,
        source: Int,
        param: UInt = TLPermissions.nToT,
        denied: Boolean = false
    ): BigInt = {
        tl.d.ready.poke(true.B)
        tl.a.bits.opcode.poke(TLOpcode.AcquireBlock)
        tl.a.bits.param.poke(param)
        tl.a.bits.size.poke(3.U)
        tl.a.bits.source.poke(source.U)
        tl.a.bits.address.poke(address.U)
        tl.a.bits.mask.poke("hff".U)
        tl.a.bits.data.poke(0.U)
        tl.a.bits.corrupt.poke(false.B)
        tl.a.valid.poke(true.B)
        tl.a.ready.expect(true.B)
        clock.step()
        tl.a.valid.poke(false.B)
        tl.d.valid.expect(true.B)
        tl.d.bits.opcode.expect(TLOpcode.GrantData)
        tl.d.bits.param.expect(param)
        tl.d.bits.source.expect(source.U)
        tl.d.bits.denied.expect(denied.B)
        val data = tl.d.bits.data.peek().litValue
        clock.step()
        data
    }

    protected def writeTlByte(
        tl: TLBundle,
        clock: Clock,
        address: BigInt,
        data: BigInt,
        source: Int = 4
    ): Unit = {
        val lane = (address & 0x7).toInt
        writeTl(
            tl = tl,
            clock = clock,
            address = address,
            data = data << (lane * 8),
            mask = 1 << lane,
            size = 0,
            source = source
        )
    }

    protected def readTlByte(tl: TLBundle, clock: Clock, address: BigInt, source: Int = 6): BigInt = {
        val lane = (address & 0x7).toInt
        (readTl(tl, clock, address, mask = 1 << lane, size = 0, source = source) >> (lane * 8)) & 0xff
    }

    protected def writeTlWord(
        tl: TLBundle,
        clock: Clock,
        address: BigInt,
        data: BigInt,
        source: Int = 3
    ): Unit = {
        val lane = (address & 0x7).toInt
        writeTl(
            tl = tl,
            clock = clock,
            address = address,
            data = data << (lane * 8),
            mask = 0xf << lane,
            size = 2,
            source = source
        )
    }

    protected def readTlWord(tl: TLBundle, clock: Clock, address: BigInt, source: Int = 4): BigInt = {
        val lane = (address & 0x7).toInt
        (readTl(tl, clock, address, mask = 0xf << lane, size = 2, source = source) >> (lane * 8)) &
            BigInt("ffffffff", 16)
    }
}
