package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.bus.RegisterPort

/** Ordered multi-outstanding DataPort to memory/RegisterPort bridge. See docs/core-mmio.md. */
class CoreRegisterRouter(base: BigInt, bytes: BigInt = 16384, capacity: Int = 8) extends Module {
    require(base >= 0 && base % 8 == 0 && bytes > 0 && bytes % 8 == 0 && base + bytes <= (BigInt(1) << 64))
    require(capacity >= 2)
    val io = IO(new Bundle {
        val upstream  = Flipped(new DataPort)
        val memory    = new DataPort
        val registers = new RegisterPort
    })
    class Owner extends Bundle {
        val local  = Bool()
        val offset = UInt(3.W)
    }
    val owners  = Module(new Queue(new Owner, capacity, pipe = false, flow = false))
    val request = io.upstream.request.bits
    val local   = !request.atomic && request.address >= base.U && request.address < (base + bytes).U(65.W)
    val shift   = Cat(request.address(2, 0), 0.U(3.W))
    io.memory.request.valid              := io.upstream.request.valid && owners.io.enq.ready && !local
    io.memory.request.bits               := request
    io.registers.request.valid           := io.upstream.request.valid && owners.io.enq.ready && local
    io.registers.request.bits.address    := request.address
    io.registers.request.bits.write      := request.write
    io.registers.request.bits.size       := request.size
    io.registers.request.bits.data       := request.data >> shift
    io.registers.request.bits.byteEnable := request.mask >> request.address(2, 0)
    io.upstream.request.ready := owners.io.enq.ready && Mux(local, io.registers.request.ready, io.memory.request.ready)
    owners.io.enq.valid       := io.upstream.request.fire
    owners.io.enq.bits.local  := local
    owners.io.enq.bits.offset := request.address(2, 0)
    val head = owners.io.deq.bits
    // Queue payload is undefined while empty; keep the unconditional shift in range in RTL and GSIM.
    val responseShift = Mux(owners.io.deq.valid && head.local, Cat(head.offset, 0.U(3.W)), 0.U(6.W))
    io.upstream.response.valid := owners.io.deq.valid && Mux(
        head.local,
        io.registers.response.valid,
        io.memory.response.valid
    )
    io.upstream.response.bits.data := Mux(
        head.local,
        (io.registers.response.bits.data << responseShift)(63, 0),
        io.memory.response.bits.data
    )
    io.upstream.response.bits.error := Mux(head.local, io.registers.response.bits.error, io.memory.response.bits.error)
    io.upstream.response.bits.pageFault := !head.local && io.memory.response.bits.pageFault
    io.registers.response.ready     := owners.io.deq.valid && head.local && io.upstream.response.ready
    io.memory.response.ready        := owners.io.deq.valid && !head.local && io.upstream.response.ready
    owners.io.deq.ready             := io.upstream.response.fire
}
