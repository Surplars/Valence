package soc.ip.dma

import chisel3._
import chisel3.util._
import soc.ip.bus.{RegisterPort, RegisterResponse}

/** Four-credit aligned memory copy engine. Independent of the CPU; see docs/dma.md. */
class MemoryCopyDma(
    base: BigInt = BigInt("10001000", 16),
    ramBase: BigInt = BigInt("80010000", 16),
    ramBytes: BigInt = 4096
) extends Module {
    require(base >= 0 && base % 8 == 0 && base + 40 <= (BigInt(1) << 64))
    require(
        ramBase >= 0 && ramBase % 8 == 0 && ramBytes >= 8 && ramBytes % 8 == 0 && ramBase + ramBytes <= (BigInt(
            1
        ) << 64)
    )
    val io = IO(new Bundle {
        val control = Flipped(new RegisterPort)
        val memory  = new RegisterPort
        val irq     = Output(Bool())
        val active  = Output(Bool())
    })
    val source            = RegInit(0.U(64.W))
    val destination       = RegInit(0.U(64.W))
    val length            = RegInit(0.U(64.W))
    val busy              = RegInit(false.B)
    val done              = RegInit(false.B)
    val failed            = RegInit(false.B)
    val interruptEnable   = RegInit(false.B)
    private val countBits = log2Ceil(ramBytes / 8 + 1)
    val readsSent         = RegInit(0.U(countBits.W))
    val writesSent        = RegInit(0.U(countBits.W))
    val writesDone        = RegInit(0.U(countBits.W))
    val resident          = RegInit(0.U(3.W))
    val data              = Module(new Queue(UInt(64.W), 4, pipe = false, flow = false))
    val owners            = Module(new Queue(Bool(), 4, pipe = false, flow = false))
    val locked            = RegInit(false.B)
    val lockedWrite       = Reg(Bool())
    val chooseWrite       = Mux(locked, lockedWrite, data.io.deq.valid)
    val available         = Mux(chooseWrite, data.io.deq.valid, readsSent < (length >> 3) && resident < 4.U)
    // A stalled offer remains stable even if an older response reports an error.
    io.memory.request.valid           := busy && (locked || !failed) && owners.io.enq.ready && available
    io.memory.request.bits.address    := Mux(chooseWrite, destination + (writesSent << 3), source + (readsSent << 3))
    io.memory.request.bits.data       := Mux(chooseWrite, data.io.deq.bits, 0.U)
    io.memory.request.bits.write      := chooseWrite
    io.memory.request.bits.size       := 3.U
    io.memory.request.bits.byteEnable := 255.U
    val readStart  = io.memory.request.fire && !chooseWrite
    val writeStart = io.memory.request.fire && chooseWrite
    when(io.memory.request.valid && !io.memory.request.ready) { locked := true.B; lockedWrite := chooseWrite }
    when(io.memory.request.fire) { locked := false.B }
    owners.io.enq.valid      := io.memory.request.fire
    owners.io.enq.bits       := chooseWrite
    io.memory.response.ready := owners.io.deq.valid && (owners.io.deq.bits || data.io.enq.ready)
    owners.io.deq.ready      := io.memory.response.fire
    data.io.enq.valid        := io.memory.response.valid && owners.io.deq.valid && !owners.io.deq.bits
    data.io.enq.bits         := io.memory.response.bits.data
    data.io.deq.ready        := writeStart || (failed && !locked)
    val discard = data.io.deq.fire && !writeStart
    when(readStart) { readsSent := readsSent + 1.U }
    when(writeStart) { writesSent := writesSent + 1.U }
    when(readStart =/= (writeStart || discard)) { resident := Mux(readStart, resident + 1.U, resident - 1.U) }
    when(io.memory.response.fire) {
        when(io.memory.response.bits.error) { failed := true.B }
        when(owners.io.deq.bits) { writesDone := writesDone + 1.U }
    }
    when(
        busy && !locked && !owners.io.deq.valid && !data.io.deq.valid && resident === 0.U &&
            (failed || writesDone === (length >> 3))
    ) { busy := false.B; done := true.B }
    io.irq    := interruptEnable && done
    io.active := busy
    val responses = Module(new Queue(new RegisterResponse, 2, pipe = false, flow = false))
    val r         = io.control.request.bits
    val offset    = r.address - base.U
    val known     = offset === 0.U || offset === 8.U || offset === 16.U || offset === 24.U || offset === 32.U
    val legal     = r.address >= base.U && r.address < (base + 40).U(65.W) && known &&
        r.size === 3.U && r.byteEnable === 255.U && (!r.write || (!busy && offset =/= 32.U))
    io.control.request.ready    := responses.io.enq.ready
    responses.io.enq.valid      := io.control.request.valid
    responses.io.enq.bits.error := !legal
    responses.io.enq.bits.data  := Mux(
        legal && !r.write,
        MuxLookup(offset, 0.U)(
            Seq(
                0.U  -> source,
                8.U  -> destination,
                16.U -> length,
                24.U -> (interruptEnable.asUInt << 2),
                32.U -> Cat(failed, done, busy)
            )
        ),
        0.U
    )
    io.control.response <> responses.io.deq
    val sourceEnd       = source +& length
    val destinationEnd  = destination +& length
    val descriptorLegal = length =/= 0.U && length(2, 0) === 0.U && source(2, 0) === 0.U && destination(2, 0) === 0.U &&
        source >= ramBase.U(65.W) && destination >= ramBase.U(65.W) &&
        sourceEnd <= (ramBase + ramBytes).U(65.W) && destinationEnd <= (ramBase + ramBytes).U(65.W) &&
        (sourceEnd <= destination || destinationEnd <= source)
    when(io.control.request.fire && legal && r.write) {
        switch(offset) {
            is(0.U) { source := r.data }
            is(8.U) { destination := r.data }
            is(16.U) { length := r.data }
            is(24.U) {
                interruptEnable := r.data(2)
                when(r.data(1)) { done := false.B; failed := false.B }
                when(r.data(0)) {
                    busy      := descriptorLegal; done := !descriptorLegal; failed := !descriptorLegal
                    readsSent := 0.U; writesSent       := 0.U; writesDone          := 0.U
                }
            }
        }
    }
    assert(resident <= 4.U)
}
