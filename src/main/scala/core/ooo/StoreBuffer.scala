package soc.core.ooo

import chisel3._
import chisel3.util._

/** Irrevocable head stores for explicitly guaranteed, non-faulting RAM. See docs/bare-core-ipc.md. */
class StoreBuffer(p: OooParams) extends Module {
    require(p.bufferedRamStores)
    private val n         = p.storeBufferEntries
    private val indexBits = math.max(1, log2Ceil(n))
    val io                = IO(new Bundle {
        val upstream  = Flipped(new DataPort)
        // Independently enqueue a proven non-faulting head RAM store. No response is owed.
        val fastStore = Flipped(Decoupled(new DataRequest))
        val memory    = new DataPort
        val busy      = Output(Bool())
        val forwarded = Output(Bool())
        // 0 accepted/idle, 1 held local acknowledgement, 2 forwarded read behind older reads,
        // 3 full write buffer, 4 older write not yet sent, 5 response-owner credits exhausted,
        // 6 downstream backpressure, 7 overlapping buffered bytes or serial MMIO ordering.
        val requestStallCause = Output(UInt(3.W))
    })
    val entries = Reg(Vec(n, new DataRequest))
    val head    = RegInit(0.U(indexBits.W))
    val tail    = RegInit(0.U(indexBits.W))
    val count   = RegInit(0.U(log2Ceil(n + 1).W))
    // Sent entries remain allocated and forwardable until their ordered responses arrive.
    val sending                 = RegInit(0.U(indexBits.W))
    val issued                  = RegInit(0.U(log2Ceil(n + 1).W))
    val ackValid                = RegInit(false.B)
    val ackData                 = Reg(UInt(64.W))
    // An unsent direct request owns the external port until it handshakes. A fast store
    // may enter the queue meanwhile, but it must not replace the held request on the bus.
    val directHeld              = RegInit(false.B)
    def next(index: UInt): UInt = if (n == 1) 0.U else (index + 1.U)(indexBits - 1, 0)
    val request                 = io.upstream.request
    // Decode payload independently of late issue/recovery valid. Acceptance and
    // side effects remain qualified by request.valid/fire below; invalid payload
    // need not be normalized before address-range/overlap checks.
    val size                    = request.bits.size
    val end                     = request.bits.address +& (1.U(64.W) << size)
    val ram                     = !request.bits.virtualized &&
        SpeculativeRamRange.contains(p, request.bits.address, size)
    val buffered = ram && request.bits.write && !request.bits.atomic
    val covered  = Wire(Vec(8, Bool()))
    val bytes    = Wire(Vec(8, UInt(8.W)))
    // Compare physical slots in parallel, before the age/head mux. A rotating head should
    // select one-bit match results, not a 61-bit address followed by a wide equality tree.
    val addressMatch = Wire(Vec(n, Bool()))
    for (slot <- 0 until n) {
        addressMatch(slot) := entries(slot).address(63, 3) === request.bits.address(63, 3)
    }
    for (lane <- 0 until 8) {
        var found: Bool = false.B
        var value: UInt = 0.U(8.W)
        for (age <- 0 until n) {
            val index = if (n == 1) 0.U else (head + age.U)(indexBits - 1, 0)
            val entry = entries(index)
            val hit   = age.U < count && addressMatch(index) && entry.mask(lane)
            value = Mux(hit, entry.data(8 * lane + 7, 8 * lane), value)
            found = found || hit
        }
        covered(lane) := found
        bytes(lane)   := value
    }
    val fastEnd = io.fastStore.bits.address +& (1.U(64.W) << io.fastStore.bits.size)
    val overlapsFastStore = io.fastStore.valid && request.valid &&
        request.bits.address < fastEnd && io.fastStore.bits.address < end
    val forward = ram && !request.bits.write && !request.bits.atomic && count =/= 0.U &&
        (covered.asUInt & request.bits.mask) === request.bits.mask
    // Track external response ownership without reducing the existing parallel read capacity.
    // With flow disabled, a new request cannot own a response until its owner bit
    // has crossed the queue register. This breaks the request-valid -> response-ready
    // feedback path; a zero-latency memory must hold its response until then.
    val owners = Module(new Queue(Bool(), p.memoryEntries + 1, pipe = false,
        flow = !p.registeredStoreResponseOwners))
    val reads  = RegInit(0.U(log2Ceil(p.memoryEntries + 2).W))
    val local  = (buffered || forward) && reads === 0.U && !ackValid && !overlapsFastStore &&
        !(io.fastStore.valid && buffered)
    // Disjoint RAM bytes may be read while earlier writes await responses. Keep request order and MMIO drain.
    val independentRead = ram && !request.bits.write && !request.bits.atomic && issued === count &&
        (covered.asUInt & request.bits.mask) === 0.U
    val direct = directHeld ||
        ((count === 0.U || independentRead) && !buffered && !ackValid && !overlapsFastStore)
    io.fastStore.ready := count < n.U
    // A response may free an old slot while an independent younger write is issued.
    val drainRequest = issued < count && !directHeld
    // The head store is irrevocable in the guaranteed-success RAM window. Forward it
    // to memory on the acceptance cycle when no older buffered write needs the port.
    // If memory stalls, the write remains in the buffer and drains normally.
    val flowBufferedWrite = request.valid && buffered && local && count < n.U && !drainRequest
    val flowFastWrite = io.fastStore.valid && io.fastStore.ready && !request.valid &&
        !drainRequest && !directHeld
    io.memory.request.valid := owners.io.enq.ready &&
        (drainRequest || flowBufferedWrite || flowFastWrite || (request.valid && direct))
    io.memory.request.bits  := Mux(drainRequest, if (n == 1) entries(0) else entries(sending),
        Mux(flowFastWrite, io.fastStore.bits, request.bits))
    request.ready           := Mux(
        buffered || forward,
        local && (!buffered || count < n.U),
        direct && owners.io.enq.ready && io.memory.request.ready
    )
    io.requestStallCause := Mux(!request.valid || request.ready, 0.U,
        Mux(ackValid, 1.U,
            Mux(forward && reads =/= 0.U, 2.U,
                Mux(buffered && count === n.U, 3.U,
                    Mux(count =/= 0.U && !independentRead && !buffered && !forward,
                        Mux(issued =/= count, 4.U, 7.U),
                        Mux(!owners.io.enq.ready, 5.U, 6.U))))))
    owners.io.enq.valid := io.memory.request.fire
    owners.io.enq.bits  := drainRequest || flowBufferedWrite || flowFastWrite
    val bufferResponse = owners.io.deq.valid && owners.io.deq.bits
    // Optional registered local replies can break the request/response feedback path.
    // Default profiles keep the same-cycle reply. External write ordering is unchanged.
    val immediateAck = !p.registeredLocalStoreResponses.B && request.fire && (buffered || forward)
    io.upstream.response.valid := ackValid || immediateAck ||
        (io.memory.response.valid && owners.io.deq.valid && !bufferResponse)
    // Data is observed only with response.valid. Select the local payload without
    // routing the request.fire handshake through the 64-bit response mux.
    io.upstream.response.bits.data := Mux(ackValid, ackData,
        Mux(local, Mux(forward, bytes.asUInt, 0.U), io.memory.response.bits.data))
    io.upstream.response.bits.error := !ackValid && !immediateAck && io.memory.response.bits.error
    io.upstream.response.bits.pageFault := !ackValid && !immediateAck && io.memory.response.bits.pageFault
    io.memory.response.ready := owners.io.deq.valid && (bufferResponse || (!ackValid && io.upstream.response.ready))
    owners.io.deq.ready      := io.memory.response.fire
    val enqueue   = request.fire && buffered
    val fastEnqueue = io.fastStore.fire
    val dequeue   = io.memory.response.fire && bufferResponse
    val readStart = io.memory.request.fire && !drainRequest && !flowBufferedWrite && !flowFastWrite
    val readEnd   = io.memory.response.fire && !bufferResponse
    when(request.valid && direct && !drainRequest && !flowBufferedWrite &&
        io.memory.request.valid && !io.memory.request.ready) { directHeld := true.B }
    when(request.fire && directHeld) { directHeld := false.B }
    when(directHeld) { assert(request.valid) }
    when(readStart =/= readEnd) { reads := Mux(readStart, reads + 1.U, reads - 1.U) }
    val writeStart = io.memory.request.fire && (drainRequest || flowBufferedWrite || flowFastWrite)
    when(writeStart) { sending := next(sending) }
    when(writeStart =/= dequeue) { issued := Mux(writeStart, issued + 1.U, issued - 1.U) }
    when(dequeue) {
        assert(!io.memory.response.bits.error, "platform violated guaranteed RAM write success")
        head := next(head)
    }
    when(enqueue) {
        if (n == 1) entries(0) := request.bits else entries(tail) := request.bits
        tail                   := next(tail)
    }
    when(fastEnqueue) {
        if (n == 1) entries(0) := io.fastStore.bits else entries(tail) := io.fastStore.bits
        tail := next(tail)
        assert(io.fastStore.bits.write && !io.fastStore.bits.atomic && !io.fastStore.bits.virtualized)
        assert(!io.fastStore.bits.uncached &&
            SpeculativeRamRange.contains(p, io.fastStore.bits.address, io.fastStore.bits.size))
        assert((io.fastStore.bits.address(2, 0) & ((1.U << io.fastStore.bits.size) - 1.U)) === 0.U)
        assert(!enqueue, "only one store may enter the buffer per cycle")
    }
    val anyEnqueue = enqueue || fastEnqueue
    when(anyEnqueue =/= dequeue) { count := Mux(anyEnqueue, count + 1.U, count - 1.U) }
    when(io.upstream.response.fire && ackValid) { ackValid := false.B }
    when(request.fire && (buffered || forward)) {
        ackValid := p.registeredLocalStoreResponses.B || !io.upstream.response.ready
        ackData  := Mux(forward, bytes.asUInt, 0.U)
        assert((request.bits.address(2, 0) & ((1.U << size) - 1.U)) === 0.U)
    }
    io.forwarded := request.fire && forward
    io.busy      := count =/= 0.U || ackValid || reads =/= 0.U
    assert(issued <= count && count <= n.U)
}
