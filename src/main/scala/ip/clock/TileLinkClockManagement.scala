package soc.ip.clock

import chisel3._
import chisel3.util._
import soc.bus.tilelink._

/** Native 64-bit TL-UL CSR front end. Four ordered transactions, no atomic,
  * burst or TL-C. Invalid A requests keep response order but poison the internal
  * address, preventing any side effect. Size/source/opcode are retained to D.
  */
class TileLinkClockManagement(config: CmuParams,
    params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4)) extends Module {
    require(params.addrWidth == 64 && params.dataWidth == 64 && params.sizeBits >= 2 && params.sizeBits <= 3)
    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(params))
        val resources = Vec(config.resources.size, new ClockResourceControl)
        val irq = Output(Bool())
    })
    val cmu = Module(new ClockManagementUnit(config))
    io.resources <> cmu.io.resources
    io.irq := cmu.io.irq
    io.tl.b.valid := false.B
    io.tl.b.bits := 0.U.asTypeOf(io.tl.b.bits)
    io.tl.c.ready := false.B
    io.tl.e.ready := false.B
    val owners = Module(new Queue(new Bundle {
        val source = UInt(params.sourceBits.W)
        val size = UInt(params.sizeBits.W)
        val dataResponse = Bool()
        val offset = UInt(3.W)
    }, 4, pipe = false, flow = false))
    val a = io.tl.a.bits
    val read = a.opcode === TLOpcode.Get
    val put = a.opcode === TLOpcode.PutFullData || a.opcode === TLOpcode.PutPartialData
    val accessMask = MuxLookup(a.size, 0.U(8.W))((0 to 3).map { n =>
        n.U -> ((((BigInt(1) << (1 << n)) - 1).U(8.W) << a.address(2, 0))(7, 0))
    })
    val maskLegal = Mux(a.opcode === TLOpcode.PutPartialData,
        (a.mask & ~accessMask) === 0.U, a.mask === accessMask)
    val protocolLegal = (read || put) && a.size <= 3.U && a.param === 0.U && !a.corrupt && maskLegal
    cmu.io.registers.request.valid := io.tl.a.valid && owners.io.enq.ready
    cmu.io.registers.request.bits.address := Mux(protocolLegal, a.address, (config.base + 4096).U)
    cmu.io.registers.request.bits.write := put
    cmu.io.registers.request.bits.size := a.size
    cmu.io.registers.request.bits.data := a.data >> Cat(a.address(2, 0), 0.U(3.W))
    cmu.io.registers.request.bits.byteEnable := a.mask >> a.address(2, 0)
    io.tl.a.ready := cmu.io.registers.request.ready && owners.io.enq.ready
    owners.io.enq.valid := io.tl.a.fire
    owners.io.enq.bits.source := a.source
    owners.io.enq.bits.size := a.size
    owners.io.enq.bits.offset := a.address(2, 0)
    owners.io.enq.bits.dataResponse := read || a.opcode === TLOpcode.ArithmeticData || a.opcode === TLOpcode.LogicalData
    val response = cmu.io.registers.response
    io.tl.d.valid := response.valid && owners.io.deq.valid
    io.tl.d.bits := 0.U.asTypeOf(io.tl.d.bits)
    io.tl.d.bits.opcode := Mux(owners.io.deq.bits.dataResponse, TLOpcode.AccessAckData, TLOpcode.AccessAck)
    io.tl.d.bits.size := owners.io.deq.bits.size
    io.tl.d.bits.source := owners.io.deq.bits.source
    io.tl.d.bits.denied := response.bits.error
    io.tl.d.bits.corrupt := response.bits.error && owners.io.deq.bits.dataResponse
    // Internal RegisterPort replies are right-justified. Restore TL byte lanes.
    // Natural alignment fixes the lane shift from the held request address.
    io.tl.d.bits.data := (response.bits.data << Cat(owners.io.deq.bits.offset, 0.U(3.W)))(63, 0)
    response.ready := owners.io.deq.valid && io.tl.d.ready
    owners.io.deq.ready := io.tl.d.fire
}
