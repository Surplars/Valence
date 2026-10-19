package soc.core.inorder

import chisel3._
import chisel3.util._

/** Ordered burst backend: one request produces `beats` ordered responses, including a write ack.
  * Writes have one beat and an aligned byte mask; reads increment by XLEN/8 bytes.
  * Rejected writes must have no side effect. A downstream AXI error may follow a side effect;
  * software must treat such a bus fault as fatal/recover the memory, not retry transparently.
  * No zero-cycle response is allowed. Data/mask remain aligned to XLEN lanes; access metadata
  * preserves subword MMIO semantics without changing the backend's aligned payload address.
  */
class FiveStageBurstRequest(val p: FiveStageConfig) extends Bundle {
    val address = UInt(p.xlen.W)
    val write = Bool()
    val data = UInt(p.xlen.W)
    val mask = UInt((p.xlen / 8).W)
    val beats = UInt(log2Ceil(p.cacheLineBytes / (p.xlen / 8) + 1).W)
    val size = UInt(3.W)
    val byteOffset = UInt(log2Ceil(p.xlen / 8).W)
}

class FiveStageBurstResponse(val p: FiveStageConfig) extends Bundle {
    val data = UInt(p.xlen.W)
    val error = Bool()
    val last = Bool()
}

class FiveStageBurstPort(val p: FiveStageConfig) extends Bundle {
    val request = Decoupled(new FiveStageBurstRequest(p))
    val response = Flipped(Decoupled(new FiveStageBurstResponse(p)))
}

/** Direct mapped, one-owner, synchronous byte-bank RAM cache. Hit latency: one cycle from
  * acceptance to response. Optional IF hit replacement allows one hit/cycle without enlarging queues;
  * the general data port defaults to state-only admission to break downstream READY scheduling loops.
  * Read misses use a real ordered burst, not repeated word requests or an instantaneous line oracle.
  * Stores are write-through/no-write-allocate: wait for the real error/ack before updating a hit.
  * This keeps precise store errors and needs no dirty eviction/flush protocol in the five-stage core.
  * Cacheable physical memory is explicitly bounded. MMIO bypasses all lookup/allocation.
  * Noncoherent prototype: external DMA writes need software/platform invalidation before use.
  */
class FiveStageWordCache(val p: FiveStageConfig, bytes: Int, allowHitReplacement: Boolean = false,
    trustedReadOnlyCacheability: Boolean = false) extends Module {
    require(bytes == 0 || (bytes >= 2 * p.cacheLineBytes && bytes <= 65536 && (bytes & (bytes - 1)) == 0))
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new FiveStageDataRequest(p)))
        val response = Decoupled(new FiveStageDataResponse(p))
        val memory = new FiveStageBurstPort(p)
        val invalidate = Input(Bool())
        // Private IF authorization boundary, not a software/TileLink hint.
        val readCacheable = if (trustedReadOnlyCacheability) Some(Input(Bool())) else None
        val hit = Output(Bool())
        val miss = Output(Bool())
        val bypass = Output(Bool())
        val coherence = if (p.coherentCaches) Some(new soc.bus.tilelink.TLBundle(
            soc.bus.tilelink.TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3))) else None
        val uncached = if (p.coherentCaches) Some(new I1DataPort) else None
        val lineGrant = if (p.coherentLineGrants)
            Some(Flipped(Decoupled(new soc.ip.tilelink.LineGrant(
                soc.bus.tilelink.TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3))))) else None
    })
    if (p.coherentCaches) {
        val coherent = Module(new I1CoherentWordCache(p, bytes,
            readOnly = p.coherentControlCuts && allowHitReplacement,
            trustedReadOnlyCacheability = p.coherentControlCuts && trustedReadOnlyCacheability))
        coherent.io.request <> io.request
        io.response <> coherent.io.response
        coherent.io.invalidate := io.invalidate
        coherent.io.readCacheable.foreach(_ := io.readCacheable.get)
        io.coherence.get <> coherent.io.tl
        coherent.io.lineGrant.foreach(_ <> io.lineGrant.get)
        io.uncached.get <> coherent.io.uncached
        io.hit := coherent.io.hit; io.miss := coherent.io.miss
        io.bypass := io.request.fire && io.request.bits.noAllocate
        io.memory.request.valid := false.B
        io.memory.request.bits := 0.U.asTypeOf(io.memory.request.bits)
        io.memory.response.ready := true.B
    } else {
    val idle :: lookup :: send :: receive :: reply :: Nil = Enum(5)
    val state = RegInit(idle)
    val saved = Reg(new FiveStageDataRequest(p))
    val result = Reg(new FiveStageDataResponse(p))
    val savedCacheable = RegInit(false.B)
    val writeHit = RegInit(false.B)
    val fillKilled = RegInit(false.B)
    val writeLookupPending = if (p.overlapWriteLookup && bytes > 0) Some(RegInit(false.B)) else None
    val failed = RegInit(false.B)
    val offsetBits = log2Ceil(p.xlen / 8)
    val lineBits = log2Ceil(p.cacheLineBytes)
    val wordsPerLine = p.cacheLineBytes / (p.xlen / 8)
    val beatBits = math.max(1, log2Ceil(wordsPerLine))
    val beat = RegInit(0.U(beatBits.W))
    val hit = WireDefault(false.B)
    val ramWord = WireDefault(0.U(p.xlen.W))
    val ramWritePending = if (p.fpgaTimingCuts && bytes > 0) Some(RegInit(false.B)) else None
    val inWindow = if (p.fpgaTimingCuts)
        I1AddressWindow.contains(io.request.bits.address, p.cacheableBase, p.cacheableBytes)
        else io.request.bits.address >= p.cacheableBase.U &&
            io.request.bits.address < (p.cacheableBase + p.cacheableBytes).U
    val cacheable = (bytes > 0).B && (if (trustedReadOnlyCacheability) io.readCacheable.get
        else !io.request.bits.noAllocate && inWindow)
    io.response.valid := state === reply || (state === lookup && hit && !saved.write)
    io.response.bits := result
    io.response.bits.pageFault := false.B
    io.response.bits.fetchSpan := false.B
    // Hit qualifies VALID, not RAM data selection. Removing the tag compare
    // from this wide mux breaks tag -> data -> parcel decode scheduling.
    // A miss cannot consume this data because response.valid remains low.
    when(state === lookup && !saved.write) {
        io.response.bits.data := ramWord; io.response.bits.error := false.B
    }
    io.request.ready := (if (allowHitReplacement)
        state === idle || (io.response.fire && !ramWritePending.getOrElse(false.B)) else state === idle)
    val tagLookup = state === lookup || writeLookupPending.getOrElse(false.B)
    io.hit := tagLookup && hit
    io.miss := tagLookup && !hit
    io.bypass := io.request.fire && !cacheable
    io.memory.request.valid := state === send
    io.memory.request.bits.address := Mux(savedCacheable && !saved.write,
        (saved.address >> lineBits) << lineBits, (saved.address >> offsetBits) << offsetBits)
    io.memory.request.bits.write := saved.write
    io.memory.request.bits.data := saved.data
    io.memory.request.bits.mask := saved.mask
    io.memory.request.bits.beats := Mux(savedCacheable && !saved.write, wordsPerLine.U, 1.U)
    io.memory.request.bits.size := Mux(savedCacheable && !saved.write, offsetBits.U, saved.size)
    io.memory.request.bits.byteOffset := Mux(savedCacheable && !saved.write, 0.U,
        saved.address(offsetBits - 1, 0))
    io.memory.response.ready := state === receive
    when(io.request.fire) {
        saved := io.request.bits; savedCacheable := cacheable; writeHit := false.B
        state := (if (p.overlapWriteLookup) Mux(cacheable && !io.request.bits.write, lookup, send)
            else Mux(cacheable, lookup, send))
        beat := 0.U; failed := false.B; fillKilled := io.invalidate
        writeLookupPending.foreach(_ := cacheable && io.request.bits.write)
    }
    writeLookupPending.foreach { waiting =>
        // Tag RAM output belongs to the request accepted at the previous edge. Capture it ONCE,
        // even if the burst request is backpressured; later disabled RAM reads are unspecified.
        when(waiting) { writeHit := hit && !io.invalidate; waiting := false.B }
    }
    when(state === lookup) {
        when(hit && !saved.write) {
            when(!io.response.ready) { result.data := ramWord; result.error := false.B; state := reply }
        }.otherwise { writeHit := hit && saved.write; state := send }
    }
    when(io.memory.request.fire) { state := receive }
    when(io.memory.response.fire) {
        failed := failed || io.memory.response.bits.error
        val desiredBeat = if (wordsPerLine == 1) 0.U else saved.address(lineBits - 1, offsetBits)
        when(!savedCacheable || saved.write || beat === desiredBeat) {
            result.data := io.memory.response.bits.data
        }
        when(io.memory.response.bits.last) {
            result.error := failed || io.memory.response.bits.error; state := reply
        }.otherwise { beat := beat + 1.U }
    }
    // Response consumption may install the next owner at the same edge. Do not erase it.
    when(io.response.fire && !io.request.fire) { state := idle }
    when(io.invalidate && state =/= idle) { fillKilled := true.B }
    if (bytes > 0) {
        val sets = bytes / p.cacheLineBytes
        val indexBits = log2Ceil(sets)
        val tagBits = p.xlen - lineBits - indexBits
        val ramAddressBits = log2Ceil(bytes / (p.xlen / 8))
        val data = SyncReadMem(bytes / (p.xlen / 8), Vec(p.xlen / 8, UInt(8.W)))
        val tags = SyncReadMem(sets, UInt(tagBits.W))
        chisel3.experimental.annotate(this)(Seq(firrtl.AttributeAnnotation(this.toNamed,
            "ram_style = \"block\"")))
        val valid = RegInit(0.U(sets.W))
        def set(address: UInt): UInt = address(lineBits + indexBits - 1, lineBits)
        def tag(address: UInt): UInt = address(p.xlen - 1, lineBits + indexBits)
        def word(address: UInt): UInt = address(ramAddressBits + offsetBits - 1, offsetBits)
        val readEnable = io.request.fire && cacheable
        ramWord := data.read(word(io.request.bits.address), readEnable).asUInt
        val readTag = tags.read(set(io.request.bits.address), readEnable)
        hit := valid(set(saved.address)) && readTag === tag(saved.address) && !io.invalidate
        val fill = io.memory.response.fire && savedCacheable && !saved.write
        val update = io.memory.response.fire && saved.write && writeHit && !io.memory.response.bits.error
        val fillWord = (word(saved.address) >> log2Ceil(wordsPerLine)) << log2Ceil(wordsPerLine) | beat
        val writeData = Mux(update, saved.data, io.memory.response.bits.data)
        val mask = Mux(update, saved.mask, ((BigInt(1) << (p.xlen / 8)) - 1).U)
        val writeAddress = Mux(update, word(saved.address), fillWord)
        if (p.fpgaTimingCuts) {
            // One beat of RAM-write scheduling, NOT another transaction owner.
            // Consecutive refill beats still write one per cycle. Last-beat hit
            // replacement is held until the scheduled write is drained, avoiding
            // undefined same-address read/write data without relying on vendor mode.
            val heldData = RegEnable(writeData, fill || update)
            val heldMask = RegEnable(mask, fill || update)
            val heldAddress = RegEnable(writeAddress, fill || update)
            ramWritePending.get := fill || update
            when(ramWritePending.get) {
                data.write(heldAddress, heldData.asTypeOf(Vec(p.xlen / 8, UInt(8.W))), heldMask.asBools)
            }
        } else when(fill || update) {
            data.write(writeAddress, writeData.asTypeOf(Vec(p.xlen / 8, UInt(8.W))), mask.asBools)
        }
        when(fill && io.memory.response.bits.last && !failed && !io.memory.response.bits.error &&
            !fillKilled && !io.invalidate) {
            tags.write(set(saved.address), tag(saved.address))
            valid := valid | UIntToOH(set(saved.address), sets)
        }
        // Never expose the old tag after its payload has been partially overwritten by a failed refill.
        when(state === lookup && !hit && !saved.write) { valid := valid & ~UIntToOH(set(saved.address), sets) }
        // A real AXI B error can arrive after external bytes changed. Do not publish the old
        // cached value after the precise fault; invalidate the hit without inventing a successful ack.
        when(io.memory.response.fire && saved.write && writeHit && io.memory.response.bits.error) {
            valid := valid & ~UIntToOH(set(saved.address), sets)
        }
        // A PMP-boundary scalar write may deliberately bypass a line previously filled in M-mode.
        // Invalidate at admission, before any real ack/error, so later cacheable reads cannot see stale bytes.
        when(io.request.fire && io.request.bits.write && io.request.bits.noAllocate) {
            valid := valid & ~UIntToOH(set(io.request.bits.address), sets)
        }
        when(io.invalidate) { valid := 0.U }
    }
    when(!reset.asBool) {
        if (trustedReadOnlyCacheability) when(io.request.fire) {
            assert(!io.request.bits.write && !io.request.bits.atomic, "trusted IF cache port must remain read-only")
            assert(io.readCacheable.get === (!io.request.bits.noAllocate && inWindow),
                "trusted IF cacheability contradicts physical/noAllocate policy")
        }
        assert(!io.request.fire || !io.request.bits.atomic, "raw atomic reached cache without physical atomic owner")
        assert(!io.memory.response.valid || state === receive, "cache received an unowned burst response")
        when(io.memory.response.fire) {
            val expectedLast = !savedCacheable || saved.write || beat === (wordsPerLine - 1).U
            assert(io.memory.response.bits.last === expectedLast, "cache burst length/last mismatch")
        }
    }
    }
}
