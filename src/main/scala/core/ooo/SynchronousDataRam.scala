package soc.core.ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.loadMemoryFromFileInline

/** Single-port synchronous byte-write RAM with an elastic response. See docs/fpga-bringup.md. */
class SynchronousDataRam(
    bytes: Int = 4096,
    base: BigInt = BigInt("80010000", 16),
    initFile: String = "",
    responseDelay: Int = 0,
    delayedResponses: Int = 8,
    programmable: Boolean = false
)
    extends Module {
    require(bytes >= 16 && isPow2(bytes))
    require(base >= 0 && base % 8 == 0 && base + bytes <= (BigInt(1) << 64))
    require(responseDelay >= 0 && responseDelay < (1 << 30))
    require(delayedResponses >= 2)
    val io = IO(new Bundle {
        val port = Flipped(new DataPort)
        val busy = Output(Bool())
        val program = if (programmable) Some(Input(Valid(new Bundle {
            val index = UInt(log2Ceil(bytes / 8).W)
            val data = UInt(64.W)
        }))) else None
    })
    val memory = SyncReadMem(bytes / 8, Vec(8, UInt(8.W)))
    if (initFile.nonEmpty) loadMemoryFromFileInline(memory, initFile)
    io.program.foreach { program =>
        when(program.valid) {
            assert(!io.port.request.valid, "RAM programming must not overlap normal access")
        }
    }
    // Registered credits cover the synchronous read stage plus the elastic response queue.
    // Request readiness must not depend on response.ready: LSU adapters also support zero-cycle slaves.
    val credits = RegInit(0.U(2.W))
    val error   = Reg(Bool())
    val reading = Reg(Bool())
    val request = io.port.request
    val size    = Mux(request.valid, request.bits.size, 0.U)
    val address = request.bits.address
    val end     = address +& (1.U(64.W) << size)
    val lowMask = MuxLookup(size, 255.U(8.W))(Seq(0.U -> 1.U, 1.U -> 3.U, 2.U -> 15.U))
    val lanes   = (lowMask << address(2, 0))(7, 0)
    val aligned = (address(2, 0) & ((1.U << size) - 1.U)) === 0.U
    val legal   = address >= base.U(65.W) && end <= (base + bytes).U(65.W) &&
        !request.bits.atomic && aligned && request.bits.mask === lanes
    request.ready := credits < 2.U
    val index  = ((address - base.U) >> 3)(log2Ceil(bytes / 8) - 1, 0)
    val result = memory.read(index, request.fire && legal && !request.bits.write).asUInt
    val normalWrite = request.fire && legal && request.bits.write
    val programWrite = io.program.map(_.valid).getOrElse(false.B)
    val writeIndex = io.program.map(program => Mux(programWrite, program.bits.index, index)).getOrElse(index)
    val writeData = io.program.map(program => Mux(programWrite, program.bits.data, request.bits.data))
        .getOrElse(request.bits.data)
    val writeMask = Mux(programWrite, 255.U(8.W), request.bits.mask)
    when(programWrite || normalWrite) {
        memory.write(writeIndex, writeData.asTypeOf(Vec(8, UInt(8.W))), writeMask.asBools)
    }
    val responses  = Module(new Queue(new DataResponse, 2, pipe = false, flow = true))
    val stageValid = RegNext(request.fire, false.B)
    responses.io.enq.valid      := stageValid
    responses.io.enq.bits.error := error
    responses.io.enq.bits.pageFault := false.B
    responses.io.enq.bits.data  := Mux(reading && !error, result, 0.U)
    val delayedPending = WireDefault(false.B)
    val internalResponseFire = if (responseDelay == 0) {
        io.port.response <> responses.io.deq
        io.port.response.fire
    } else {
        // Test/bring-up model of an ordered, pipelined external memory return path.
        // Responses leave the SRAM immediately, so its two credits can be reused
        // while earlier responses wait in this queue. The queue holds one beat per entry.
        class TimedResponse extends Bundle {
            val response = new DataResponse
            val due      = UInt(32.W)
        }
        val cycle = RegInit(0.U(32.W))
        cycle := cycle + 1.U
        val delayed = Module(new Queue(new TimedResponse, delayedResponses, pipe = false, flow = false))
        delayedPending := delayed.io.deq.valid
        delayed.io.enq.valid         := responses.io.deq.valid
        delayed.io.enq.bits.response := responses.io.deq.bits
        delayed.io.enq.bits.due      := cycle + responseDelay.U
        responses.io.deq.ready      := delayed.io.enq.ready
        val elapsed = cycle - delayed.io.deq.bits.due
        io.port.response.valid      := delayed.io.deq.valid && !elapsed(31)
        io.port.response.bits       := delayed.io.deq.bits.response
        delayed.io.deq.ready        := io.port.response.ready && !elapsed(31)
        responses.io.deq.fire
    }
    when(stageValid) { assert(responses.io.enq.ready, "RAM response capacity invariant") }
    when(request.fire =/= internalResponseFire) {
        credits := Mux(request.fire, credits + 1.U, credits - 1.U)
    }
    when(request.fire) {
        error   := !legal
        reading := !request.bits.write
    }
    io.busy := credits =/= 0.U || delayedPending
    assert(credits <= 2.U)
}
