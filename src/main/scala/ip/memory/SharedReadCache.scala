package soc.ip.memory

import chisel3._
import chisel3.util._
import soc.ip.bus.RegisterResponse

/** Mutually prioritized upstream block reasons plus independent downstream pressure events. */
class CacheStallEvents extends Bundle {
    val full          = Bool()
    val exclusive     = Bool()
    val serialized    = Bool()
    val sameBeat      = Bool()
    val fill          = Bool()
    val lowerCapacity = Bool()
    val lowerReady    = Bool()
}

/** Ordered, write-through shared read cache with pipelined hits and four outstanding misses. */
class SharedReadCache(base: BigInt = BigInt("80010000", 16), bytes: BigInt = 4096, lines: Int = 16) extends Module {
    require(base >= 0 && base % 64 == 0 && bytes >= 64 && bytes % 64 == 0 && base + bytes <= (BigInt(1) << 64))
    require(lines >= 2 && lines <= 256 && isPow2(lines))
    private val indexBits     = log2Ceil(lines)
    private val capacity      = 8
    private val lowerCapacity = 4
    val io                    = IO(new Bundle {
        val upstream = Flipped(new MemoryBeatPort)
        val memory   = new MemoryBeatPort
        val hit      = Output(Bool())
        val miss     = Output(Bool())
        val stalls   = Output(new CacheStallEvents)
    })

    // These slots restore request order after hit and lower-memory paths finish at different times.
    val operations       = Reg(Vec(capacity, new MemoryBeatRequest))
    val results          = Reg(Vec(capacity, new RegisterResponse))
    val active           = RegInit(VecInit(Seq.fill(capacity)(false.B)))
    val complete         = RegInit(VecInit(Seq.fill(capacity)(false.B)))
    val needsLower       = Reg(Vec(capacity, Bool()))
    val fill             = Reg(Vec(capacity, Bool()))
    val head             = RegInit(0.U(3.W))
    val tail             = RegInit(0.U(3.W))
    val issue            = RegInit(0.U(3.W))
    val count            = RegInit(0.U(4.W))
    val unissued         = RegInit(0.U(4.W))
    val lowerOutstanding = RegInit(0.U(3.W))
    val exclusive        = RegInit(false.B)
    val lowerOwners      = Module(new Queue(UInt(3.W), lowerCapacity, pipe = false, flow = true))

    val tags                           = Reg(Vec(lines, UInt((64 - 6 - indexBits).W)))
    val valid                          = RegInit(VecInit(Seq.fill(lines)(0.U(8.W))))
    val data                           = SyncReadMem(lines * 8, UInt(64.W))
    def index(address: UInt): UInt     = address(5 + indexBits, 6)
    def tag(address: UInt): UInt       = address(63, 6 + indexBits)
    def sector(address: UInt): UInt    = address(5, 3)
    def wordIndex(address: UInt): UInt = address(5 + indexBits, 3)

    val r         = io.upstream.request.bits
    val mask      = MuxLookup(r.size, 255.U(8.W))(Seq(0.U -> 1.U, 1.U -> 3.U, 2.U -> 15.U))
    val cacheable = r.address >= base.U(65.W) &&
        (r.address +& (1.U(64.W) << r.size)) <= (base + bytes).U(65.W) &&
        (r.address(2, 0) & ((1.U << r.size) - 1.U)) === 0.U && r.mask === (mask << r.address(2, 0))(7, 0)
    val readCandidate = cacheable && !r.write
    val tagHit        = tags(index(r.address)) === tag(r.address) && valid(index(r.address))(sector(r.address))
    // A second request for an unresolved beat waits for its fill, avoiding redundant physical reads.
    val sameBeatPending = VecInit((0 until capacity).map { i =>
        active(i) && fill(i) && !complete(i) && operations(i).address(63, 3) === r.address(63, 3)
    }).asUInt.orR
    // A fill only conflicts with a simultaneous read of the same physical SRAM word.
    val fillOwner   = lowerOwners.io.deq.bits
    val fillingNow  = io.memory.response.valid && lowerOwners.io.deq.valid &&
        fill(fillOwner) && !io.memory.response.bits.error
    val fillConflict = fillingNow && wordIndex(operations(fillOwner).address) === wordIndex(r.address)
    // Cacheable writes invalidate at acceptance, but must wait for every older
    // read to finish its lookup or fill. Older unfinished writes can be queued;
    // lower requests and upstream responses preserve their original order.
    val unfinishedRead = VecInit((0 until capacity).map { i =>
        active(i) && !complete(i) && !operations(i).write
    }).asUInt.orR
    // Uncacheable requests still start only after the return queue drains.
    val canStartExclusive = Mux(r.write && cacheable, !unfinishedRead, count === 0.U)
    io.stalls.full       := io.upstream.request.valid && count === capacity.U
    io.stalls.exclusive  := io.upstream.request.valid && !io.stalls.full && exclusive
    io.stalls.serialized := io.upstream.request.valid && !io.stalls.full && !exclusive &&
        !readCandidate && !canStartExclusive
    io.stalls.sameBeat := io.upstream.request.valid && !io.stalls.full && !exclusive &&
        readCandidate && sameBeatPending
    io.stalls.fill := io.upstream.request.valid && !io.stalls.full && !exclusive &&
        readCandidate && !sameBeatPending && fillConflict
    io.upstream.request.ready := count < capacity.U && !exclusive &&
        (readCandidate || canStartExclusive) && !(readCandidate && (sameBeatPending || fillConflict))
    val accepted    = io.upstream.request.fire
    val read        = data.read(wordIndex(r.address), accepted && readCandidate)
    val lookupValid = RegNext(accepted && readCandidate, false.B)
    val lookupHit   = RegEnable(tagHit, accepted && readCandidate)
    val lookupSlot  = RegEnable(tail, accepted && readCandidate)
    io.hit  := lookupValid && lookupHit
    io.miss := lookupValid && !lookupHit

    when(accepted) {
        operations(tail) := r
        active(tail)     := true.B
        complete(tail)   := false.B
        needsLower(tail) := !readCandidate || !tagHit
        fill(tail)       := readCandidate && !tagHit
        tail             := tail + 1.U
        when(!readCandidate && !(r.write && cacheable)) { exclusive := true.B }
        when(r.write && tags(index(r.address)) === tag(r.address)) {
            valid(index(r.address)) := Mux(cacheable, valid(index(r.address)) & ~UIntToOH(sector(r.address), 8), 0.U)
        }
    }
    when(lookupValid && lookupHit) {
        results(lookupSlot).data  := read
        results(lookupSlot).error := false.B
        complete(lookupSlot)      := true.B
    }

    val skipHit = unissued =/= 0.U && !needsLower(issue)
    io.memory.request.valid  := unissued =/= 0.U && needsLower(issue) && lowerOutstanding < lowerCapacity.U
    io.stalls.lowerCapacity  := unissued =/= 0.U && needsLower(issue) && lowerOutstanding === lowerCapacity.U
    io.stalls.lowerReady     := io.memory.request.valid && !io.memory.request.ready
    io.memory.request.bits   := operations(issue)
    lowerOwners.io.enq.valid := io.memory.request.fire
    lowerOwners.io.enq.bits  := issue
    when(io.memory.request.valid) { assert(lowerOwners.io.enq.ready, "lower owner capacity") }
    val advanced = skipHit || io.memory.request.fire
    when(advanced) { issue := issue + 1.U }
    when(accepted =/= advanced) { unissued := Mux(accepted, unissued + 1.U, unissued - 1.U) }

    io.memory.response.ready := lowerOwners.io.deq.valid
    lowerOwners.io.deq.ready := io.memory.response.fire
    when(io.memory.request.fire =/= io.memory.response.fire) {
        lowerOutstanding := Mux(io.memory.request.fire, lowerOutstanding + 1.U, lowerOutstanding - 1.U)
    }
    when(io.memory.response.fire) {
        val owner = lowerOwners.io.deq.bits
        results(owner)  := io.memory.response.bits
        complete(owner) := true.B
        when(exclusive) { exclusive := false.B }
        when(fill(owner) && !io.memory.response.bits.error) {
            val address = operations(owner).address
            val i       = index(address)
            val same    = tags(i) === tag(address)
            tags(i)  := tag(address)
            valid(i) := Mux(same, valid(i), 0.U) | UIntToOH(sector(address), 8)
            data.write(wordIndex(address), io.memory.response.bits.data)
        }
    }

    // The synchronous SRAM result is available in the lookup cycle. A hit at the ordered
    // response head can bypass the extra result register without bypassing the SRAM boundary.
    val headHit = lookupValid && lookupHit && lookupSlot === head && count =/= 0.U && !complete(head)
    // A lower response for the return head can use the same ordered bypass. The lower response is
    // consumed regardless of upstream readiness; the existing result slot holds it under backpressure.
    val headLower = io.memory.response.valid && lowerOwners.io.deq.valid &&
        lowerOwners.io.deq.bits === head && count =/= 0.U && !complete(head)
    io.upstream.response.valid := count =/= 0.U && (complete(head) || headHit || headLower)
    io.upstream.response.bits.data := Mux(headHit, read,
        Mux(headLower, io.memory.response.bits.data, results(head).data))
    io.upstream.response.bits.error := !headHit &&
        Mux(headLower, io.memory.response.bits.error, results(head).error)
    when(io.upstream.response.fire) {
        active(head)   := false.B
        complete(head) := false.B
        head           := head + 1.U
    }
    when(accepted =/= io.upstream.response.fire) {
        count := Mux(accepted, count + 1.U, count - 1.U)
    }
    assert(count <= capacity.U && unissued <= count && lowerOutstanding <= lowerCapacity.U)
}
