package soc.ip.bus

import chisel3._
import chisel3.util._

/** Exact non-flow/non-pipe FIFO with an optional selected-field head mirror.
  * Empty selectedBits means the complete payload. Residual fields use a current-
  * head read with the same pointers/count/handshake; they never own another queue.
  * The mirror adds no capacity. A full pop still refuses simultaneous enqueue.
  */
class MirroredHeadQueue[T <: Data](gen: T, entries: Int, selectedBits: Seq[Int] = Seq.empty) extends Module {
    require(entries >= 2)
    val io = IO(new QueueIO(gen, entries))
    private val pointerBits = log2Ceil(entries)
    private val width = gen.getWidth
    private val selected = if (selectedBits.isEmpty) (0 until width).toSeq else selectedBits.sorted
    require(selected.distinct.size == selected.size && selected.forall(i => i >= 0 && i < width))
    private val residual = (0 until width).filterNot(selected.contains)
    def runs(indices: Seq[Int]): Seq[Seq[Int]] = indices.foldLeft(Vector.empty[Vector[Int]]) { (groups, bit) =>
        if (groups.nonEmpty && groups.last.last + 1 == bit) groups.init :+ (groups.last :+ bit)
        else groups :+ Vector(bit)
    }
    def select(bits: UInt, indices: Seq[Int]): UInt = Cat(runs(indices).reverse.map(r => bits(r.last, r.head)))
    val storage = Mem(entries, UInt(selected.size.W))
    val residualStorage = if (residual.nonEmpty) Some(Mem(entries, UInt(residual.size.W))) else None
    val head = Reg(UInt(selected.size.W))
    val enqueuePointer = RegInit(0.U(pointerBits.W))
    val dequeuePointer = RegInit(0.U(pointerBits.W))
    val count = RegInit(0.U(log2Ceil(entries + 1).W))
    def next(pointer: UInt): UInt = Mux(pointer === (entries - 1).U, 0.U, pointer + 1.U)
    val nextDequeue = next(dequeuePointer)
    // Unconditional async read: the narrow head write enable owns retention.
    val nextPayload = storage.read(nextDequeue)
    io.enq.ready := count =/= entries.U
    io.deq.valid := count =/= 0.U
    val residualHead = residualStorage.map(_.read(dequeuePointer))
    val outputRuns = (runs(selected).map(_ -> true) ++ runs(residual).map(_ -> false)).sortBy(_._1.head)
    io.deq.bits := Cat(outputRuns.reverse.map { case (r, mirrored) =>
        val indices = if (mirrored) selected else residual
        val data = if (mirrored) head else residualHead.get
        data(indices.indexOf(r.last), indices.indexOf(r.head))
    }).asTypeOf(gen)
    io.count := count
    val push = io.enq.fire
    val pop = io.deq.fire
    when(push) {
        storage.write(enqueuePointer, select(io.enq.bits.asUInt, selected))
        residualStorage.foreach(_.write(enqueuePointer, select(io.enq.bits.asUInt, residual)))
        enqueuePointer := next(enqueuePointer)
    }
    when(pop) { dequeuePointer := nextDequeue }
    // Avoid undefined read-during-write when the new owner is the next head.
    val loadIncoming = push && (count === 0.U || (count === 1.U && pop))
    val loadBuffered = pop && count > 1.U
    when(loadIncoming || loadBuffered) { head := Mux(loadIncoming, select(io.enq.bits.asUInt, selected), nextPayload) }
    when(push =/= pop) { count := Mux(push, count + 1.U, count - 1.U) }
    assert(count <= entries.U, "mirrored queue capacity overflow")
}
