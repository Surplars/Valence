package soc.ip.memory

import chisel3._
import chisel3.util._
import soc.ip.bus.RegisterResponse

/** Byte addresses with data/mask in lanes of the containing aligned 64-bit beat. */
class MemoryBeatRequest extends Bundle {
    val address = UInt(64.W)
    val write   = Bool()
    val size    = UInt(2.W)
    val data    = UInt(64.W)
    val mask    = UInt(8.W)
}
class MemoryBeatPort extends Bundle {
    val request  = Decoupled(new MemoryBeatRequest)
    val response = Flipped(Decoupled(new RegisterResponse))
}
class AtomicMemoryRequest extends MemoryBeatRequest {
    val atomic    = Bool()
    val operation = UInt(5.W)
}
class AtomicMemoryPort extends Bundle {
    val request  = Decoupled(new AtomicMemoryRequest)
    val response = Flipped(Decoupled(new RegisterResponse))
}

/** Single-hart atomic memory boundary with DMA exclusion. CPU instruction integration is separate. */
class AtomicMemory(
    base: BigInt = BigInt("80010000", 16),
    bytes: BigInt = 4096,
    registerResponseOwners: Boolean = false
) extends Module {
    require(base >= 0 && base % 64 == 0 && bytes >= 64 && bytes % 64 == 0 && base + bytes <= (BigInt(1) << 64))
    val io = IO(new Bundle {
        val cpu              = Flipped(new AtomicMemoryPort)
        val dma              = Flipped(new MemoryBeatPort)
        val memory           = new MemoryBeatPort
        val memoryRequestCpu = Output(Bool())
        val clearReservation = Input(Bool())
    })
    val idle :: readRequest :: readResponse :: writeRequest :: writeResponse :: finish :: Nil = Enum(6)
    val state                                                                                 = RegInit(idle)
    val operation          = Reg(new AtomicMemoryRequest)
    val writeValue         = Reg(UInt(64.W))
    val result             = Reg(new RegisterResponse)
    val reserved           = RegInit(false.B)
    val reservationCleared = RegInit(false.B)
    val reservedAddress    = Reg(UInt(64.W))
    val reservedSize       = Reg(UInt(2.W))
    // Register only ordinary CPU/DMA response ownership, not the data or atomic FSM.
    // With this opt-in, a zero-cycle manager must hold its response until ready;
    // a manager already taking at least one cycle has unchanged response latency.
    val owners             = Module(new Queue(Bool(), 8, pipe = false, flow = !registerResponseOwners))
    val turn               = RegInit(false.B)
    val locked             = RegInit(false.B)
    val lockedOwner        = Reg(Bool())
    val selected           =
        Mux(locked, lockedOwner, Mux(io.cpu.request.valid && io.dma.request.valid, turn, io.dma.request.valid))
    val wantsAtomic = !selected && io.cpu.request.valid && io.cpu.request.bits.atomic
    val ordinary    = Wire(new MemoryBeatRequest)
    ordinary := io.dma.request.bits
    // Explicit assignments avoid depending on extended-Bundle bit layout.
    when(!selected) {
        ordinary.address := io.cpu.request.bits.address
        ordinary.write   := io.cpu.request.bits.write
        ordinary.size    := io.cpu.request.bits.size
        ordinary.data    := io.cpu.request.bits.data
        ordinary.mask    := io.cpu.request.bits.mask
    }
    val normal = state === idle && !wantsAtomic
    io.memoryRequestCpu := state =/= idle || !selected
    io.memory.request.valid := normal && Mux(
        selected,
        io.dma.request.valid,
        io.cpu.request.valid
    ) && owners.io.enq.ready
    io.memory.request.bits := ordinary
    io.cpu.request.ready   := state === idle && !selected && Mux(
        wantsAtomic,
        owners.io.count === 0.U,
        owners.io.enq.ready && io.memory.request.ready
    )
    io.dma.request.ready := normal && selected && owners.io.enq.ready && io.memory.request.ready
    owners.io.enq.valid  := normal && io.memory.request.fire
    owners.io.enq.bits   := selected
    io.cpu.response.valid := state === finish || (state === idle && owners.io.deq.valid && !owners.io.deq.bits && io.memory.response.valid)
    io.cpu.response.bits     := Mux(state === finish, result, io.memory.response.bits)
    io.dma.response.valid    := state === idle && owners.io.deq.valid && owners.io.deq.bits && io.memory.response.valid
    io.dma.response.bits     := io.memory.response.bits
    io.memory.response.ready := state === idle && owners.io.deq.valid && Mux(
        owners.io.deq.bits,
        io.dma.response.ready,
        io.cpu.response.ready
    )
    owners.io.deq.ready := state === idle && io.memory.response.fire
    when(normal && io.memory.request.valid && !io.memory.request.ready) { locked := true.B; lockedOwner := selected }
    when(normal && io.memory.request.fire) {
        locked := false.B
        turn   := !selected
        when(ordinary.write && ordinary.address(63, 6) === reservedAddress(63, 6)) { reserved := false.B }
    }
    val r     = io.cpu.request.bits
    val isLr  = r.operation === 2.U
    val isSc  = r.operation === 3.U
    val known = Seq(0, 1, 2, 3, 4, 8, 12, 16, 20, 24, 28).map(n => r.operation === n.U).reduce(_ || _)
    val mask  = Mux(r.size === 2.U, (15.U(8.W) << r.address(2, 0))(7, 0), 255.U)
    val legal = known && r.size >= 2.U && (r.address(2, 0) & Mux(r.size === 2.U, 3.U, 7.U)) === 0.U &&
        r.address >= base.U(65.W) && (r.address +& (1.U(64.W) << r.size)) <= (base + bytes).U(65.W) && r.mask === mask
    val matches = reserved && !io.clearReservation && r.address === reservedAddress && r.size === reservedSize
    when(io.cpu.request.fire && r.atomic) {
        assert(owners.io.count === 0.U, "atomic operation started before normal responses drained")
        operation          := r
        reservationCleared := io.clearReservation
        writeValue         := r.data
        result.data        := 0.U
        result.error       := !legal
        turn               := true.B
        state              := Mux(!legal || (isSc && !matches), finish, Mux(isSc, writeRequest, readRequest))
        when(legal && isSc && !matches) { result.data := 1.U }
        when(isLr || isSc || r.address(63, 6) === reservedAddress(63, 6)) { reserved := false.B }
    }
    val issuing = state === readRequest || state === writeRequest
    when(issuing) {
        io.memory.request.valid        := true.B
        io.memory.request.bits.address := operation.address
        io.memory.request.bits.write   := state === writeRequest
        io.memory.request.bits.size    := operation.size
        io.memory.request.bits.mask := Mux(operation.size === 2.U, (15.U(8.W) << operation.address(2, 0))(7, 0), 255.U)
        io.memory.request.bits.data := writeValue << Cat(operation.address(2, 0), 0.U(3.W))
    }
    val reading = state === readResponse || state === readRequest
    when(state =/= idle && state =/= finish) {
        io.memory.response.ready := state === readResponse || state === writeResponse || (issuing && io.memory.request.ready)
    }
    when(issuing && io.memory.request.fire) { state := Mux(reading, readResponse, writeResponse) }
    val shifted  = io.memory.response.bits.data >> Cat(operation.address(2, 0), 0.U(3.W))
    val word     = operation.size === 2.U
    val oldValue = Mux(word, Cat(Fill(32, shifted(31)), shifted(31, 0)), shifted)
    val operand  = Mux(word, Cat(Fill(32, operation.data(31)), operation.data(31, 0)), operation.data)
    val computed = MuxLookup(operation.operation, operand)(
        Seq(
            0.U  -> (oldValue + operand),
            4.U  -> (oldValue ^ operand),
            8.U  -> (oldValue | operand),
            12.U -> (oldValue & operand),
            16.U -> Mux(oldValue.asSInt < operand.asSInt, oldValue, operand),
            20.U -> Mux(oldValue.asSInt > operand.asSInt, oldValue, operand),
            24.U -> Mux(oldValue < operand, oldValue, operand),
            28.U -> Mux(oldValue > operand, oldValue, operand)
        )
    )
    when(state =/= idle && state =/= finish && io.memory.response.fire) {
        result.error := io.memory.response.bits.error
        when(reading) {
            result.data := oldValue
            when(io.memory.response.bits.error || operation.operation === 2.U) {
                state := finish
                when(!io.memory.response.bits.error && operation.operation === 2.U && !reservationCleared) {
                    reserved := true.B; reservedAddress := operation.address; reservedSize := operation.size
                }
            }.otherwise { writeValue := computed; state := writeRequest }
        }.otherwise { state := finish }
    }
    when(state === finish && io.cpu.response.fire) { state := idle }
    when(io.clearReservation) {
        reserved := false.B
        when(state =/= idle) { reservationCleared := true.B }
    }
}
