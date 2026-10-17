package soc.core.ooo

import chisel3._
import chisel3.util._

/** CPU-local reservations, unrelated to ROB generations or TileLink/AXI IDs.
  * A slot's handle cannot be reused while its previous actual reply is outstanding.
  */
case class CpuReturnConfig(memoryEntries: Int, storeBufferEntries: Int, fpEnabled: Boolean) {
    require(memoryEntries > 0 && storeBufferEntries > 0)
    val handleCount: Int = memoryEntries + storeBufferEntries + (if (fpEnabled) 1 else 0)
    val handleBits: Int = math.max(1, log2Ceil(handleCount))
    val tableEntries: Int = 1 << handleBits
    val fpHandle: Int = memoryEntries + storeBufferEntries
    def integer(handle: UInt): Bool = handle < memoryEntries.U
    def store(handle: UInt): Bool = handle >= memoryEntries.U && handle < fpHandle.U
    def legal(handle: UInt): Bool = handle < handleCount.U
    def storeHandle(index: UInt): UInt = (memoryEntries.U(handleBits.W) + index)(handleBits - 1, 0)
}

/** Explicit payload-only adapters at the tagged CPU protocol's two ends. */
object CpuReturnTransport {
    // Preserve the existing test-visible owner interface without retaining a
    // second FIFO when enabled. This is a Scala view of wires, not storage.
    class Owners[T <: Data](val io: QueueIO[T])
    def ownerView[T <: Data](gen: T, entries: Int): Owners[T] =
        new Owners(Wire(new QueueIO(gen, entries)))
    def orderedOwners[T <: Data](view: Owners[T], gen: T, entries: Int, flow: Boolean): Unit = {
        val queue = Module(new Queue(gen, entries, pipe = false, flow = flow)).suggestName("owners")
        queue.io.enq.valid := view.io.enq.valid
        queue.io.enq.bits := view.io.enq.bits
        view.io.enq.ready := queue.io.enq.ready
        view.io.deq.valid := queue.io.deq.valid
        view.io.deq.bits := queue.io.deq.bits
        queue.io.deq.ready := view.io.deq.ready
        view.io.count := queue.io.count
    }
    def requestPayload(target: DataRequest, source: DataRequest): Unit = {
        target.atomic := source.atomic
        target.atomicOp := source.atomicOp
        target.address := source.address
        target.write := source.write
        target.size := source.size
        target.data := source.data
        target.mask := source.mask
        target.virtualized := source.virtualized
        target.precheckedLoad := source.precheckedLoad
        target.translationEpoch := source.translationEpoch
        target.prefetchNextAllowed := source.prefetchNextAllowed
        target.uncached := source.uncached
    }
    def responsePayload(target: DataResponse, source: DataResponse): Unit = {
        target.data := source.data
        target.error := source.error
        target.pageFault := source.pageFault
    }
    def held(response: DecoupledIO[DataResponse]): Unit = {
        val stalled = RegNext(response.valid && !response.ready, false.B)
        val previous = RegEnable(response.bits, response.valid && !response.ready)
        when(stalled) {
            assert(response.valid && response.bits.asUInt === previous.asUInt,
                "held CPU return changed payload or reservation handle")
        }
    }
}
