package soc.core.pipeline

import chisel3._
import chisel3.util._

class FrontendQueueEntry(XLEN: Int) extends Bundle {
    val pc          = UInt(XLEN.W)
    val instr       = UInt(32.W)
    val instrLen    = UInt(2.W)
    val predTaken   = Bool()
    val predTarget  = UInt(XLEN.W)
}

/** Small flushable fetch/decode buffer.
  *
  * This queue lets the frontend keep fetching during LSU or load-use stalls
  * until the buffer fills. It intentionally uses registered storage and no
  * cache-response combinational shortcuts, so it remains friendly to FPGA
  * timing and BRAM-based I-cache implementations.
  */
class FrontendQueue(XLEN: Int, entries: Int) extends Module {
    require(entries > 0, "FrontendQueue requires at least one entry")

    private val ptrWidth = math.max(1, log2Ceil(entries))
    private val countWidth = log2Ceil(entries + 1)

    val io = IO(new Bundle {
        val flush = Input(Bool())
        val enq   = Flipped(Decoupled(new FrontendQueueEntry(XLEN)))
        val deq   = Decoupled(new FrontendQueueEntry(XLEN))
        val count = Output(UInt(countWidth.W))
        val full  = Output(Bool())
        val empty = Output(Bool())
    })

    val mem = Reg(Vec(entries, new FrontendQueueEntry(XLEN)))
    val head = RegInit(0.U(ptrWidth.W))
    val tail = RegInit(0.U(ptrWidth.W))
    val count = RegInit(0.U(countWidth.W))

    private def wrapInc(ptr: UInt): UInt =
        Mux(ptr === (entries - 1).U, 0.U, ptr + 1.U)

    val empty = count === 0.U
    val full = count === entries.U
    val deqFire = io.deq.fire
    // Do not enqueue into a full queue even if this cycle also dequeues. When
    // head == tail, a same-slot read/write can let the younger fetch overwrite
    // the instruction being issued, which is especially visible with dense RVC
    // streams. Holding IF for one cycle keeps ordering unambiguous and maps
    // cleanly to FPGA registers or RAMs.
    io.enq.ready := !io.flush && !full
    io.deq.valid := !io.flush && !empty
    io.deq.bits := mem(head)
    io.count := count
    io.full := full
    io.empty := empty

    val enqFire = io.enq.fire

    when(io.flush) {
        head := 0.U
        tail := 0.U
        count := 0.U
    }.otherwise {
        when(enqFire) {
            mem(tail) := io.enq.bits
            tail := wrapInc(tail)
        }
        when(deqFire) {
            head := wrapInc(head)
        }

        switch(Cat(enqFire, deqFire)) {
            is("b10".U) { count := count + 1.U }
            is("b01".U) { count := count - 1.U }
        }
    }
}
