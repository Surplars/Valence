package soc.platform

import chisel3._
import chisel3.util._
import soc.ip.memory._

/** Pure CPU-local RAM/private-cache selection. No peripheral lives here.
  * Eight ordered owners, one request/reply per cycle, no request data stage.
  * Byte lanes and physical/atomic/translation attributes pass through unchanged.
  */
class CommonPrivateMemoryRouter(ramBase: BigInt, ramBytes: BigInt, capacity: Int = 8) extends Module {
    require(capacity >= 2 && ramBase >= 0 && ramBytes > 0)
    val io = IO(new Bundle {
        val cpu = Flipped(new NativeMemoryPort)
        val cache = new NativeMemoryPort
        val uncached = new NativeMemoryPort
        val idle = Output(Bool())
    })
    val owners = Module(new Queue(Bool(), capacity, pipe = false, flow = false))
    val address = io.cpu.request.bits.address
    val cached = address >= ramBase.U(65.W) && address < (ramBase + ramBytes).U(65.W)
    io.cache.request.valid := io.cpu.request.valid && owners.io.enq.ready && cached
    io.uncached.request.valid := io.cpu.request.valid && owners.io.enq.ready && !cached
    io.cache.request.bits := io.cpu.request.bits
    io.uncached.request.bits := io.cpu.request.bits
    io.cpu.request.ready := owners.io.enq.ready && Mux(cached, io.cache.request.ready, io.uncached.request.ready)
    owners.io.enq.valid := io.cpu.request.fire
    owners.io.enq.bits := cached
    io.cpu.response.valid := owners.io.deq.valid && Mux(owners.io.deq.bits,
        io.cache.response.valid, io.uncached.response.valid)
    io.cpu.response.bits := Mux(owners.io.deq.bits, io.cache.response.bits, io.uncached.response.bits)
    io.cache.response.ready := owners.io.deq.valid && owners.io.deq.bits && io.cpu.response.ready
    io.uncached.response.ready := owners.io.deq.valid && !owners.io.deq.bits && io.cpu.response.ready
    owners.io.deq.ready := io.cpu.response.fire
    io.idle := owners.io.count === 0.U && !io.cpu.request.valid && !io.cpu.response.valid
}

/** Ordered native requests gain an explicit transport owner; clears occupy the
  * SAME sequence as LR/SC and require a real response. Ordinary traffic retains
  * 2^ownerBits simultaneous owners, never a one-request mailbox. The fabric must
  * preserve this lane's response order. Clear pulses coalesce only until a clear
  * is enqueued, before any later architectural request can pass it.
  */
class CommonNativeOwnerAdapter(p: CommonCpuTilePortParams, carriesClear: Boolean) extends Module {
    val io = IO(new Bundle {
        val native = Flipped(new NativeMemoryPort)
        val transport = new CommonTileScalarPort(p)
        val needsCoherenceLookup = Input(Bool())
        val clearReservation = Input(Bool())
        val idle = Output(Bool())
    })
    val capacity = 1 << p.scalarOwnerBits
    val next = RegInit(0.U(p.scalarOwnerBits.W))
    val returning = RegInit(0.U(p.scalarOwnerBits.W))
    val owners = RegInit(0.U((p.scalarOwnerBits + 1).W))
    val clearPending = RegInit(false.B)
    val clear = carriesClear.B && (clearPending || io.clearReservation)
    io.transport.request.valid := owners < capacity.U && (clear || io.native.request.valid)
    io.transport.request.bits.owner := next
    io.transport.request.bits.clearReservation := clear
    io.transport.request.bits.needsCoherenceLookup := io.needsCoherenceLookup
    io.transport.request.bits.memory := io.native.request.bits
    io.native.request.ready := owners < capacity.U && !clear && io.transport.request.ready
    clearPending := clear && !io.transport.request.fire
    io.native.response.valid := io.transport.response.valid && !io.transport.response.bits.clearReservation
    io.native.response.bits := io.transport.response.bits.memory
    io.transport.response.ready := Mux(io.transport.response.bits.clearReservation, true.B, io.native.response.ready)
    when(io.transport.request.fire) { next := next + 1.U }
    when(io.transport.response.fire) {
        returning := returning + 1.U
        assert(owners =/= 0.U, "native transport response has no owner")
        assert(io.transport.response.bits.owner === returning, "native lane response order/owner mismatch")
    }
    when(io.transport.request.fire =/= io.transport.response.fire) {
        owners := Mux(io.transport.request.fire, owners + 1.U, owners - 1.U)
    }
    if (!carriesClear) { assert(!io.clearReservation, "clear supplied to an instruction-only native lane") }
    when(clear) { assert(!io.native.request.fire, "native request passed a pending reservation clear") }
    io.idle := owners === 0.U && !clear && !io.native.request.valid && !io.transport.response.valid
}
