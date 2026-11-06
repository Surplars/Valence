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
    trustedReadOnlyCacheability: Boolean = false, reportMaintenance: Boolean = false,
    reportQuiescence: Boolean = false) extends Module {
    require(!reportMaintenance || p.coherentCaches, "maintenance completion requires real coherent flush")
    require(bytes == 0 || (bytes >= 2 * p.cacheLineBytes && bytes <= 65536 && (bytes & (bytes - 1)) == 0))
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new FiveStageDataRequest(p)))
        val response = Decoupled(new FiveStageDataResponse(p))
        val memory = new FiveStageBurstPort(p)
        val invalidate = Input(Bool())
        val invalidateDone = if (reportMaintenance) Some(Output(Bool())) else None
        val quiescent = if (reportQuiescence) Some(Output(Bool())) else None
        val quiescenceRequestPending = if (reportQuiescence) Some(Input(Bool())) else None
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
            trustedReadOnlyCacheability = p.coherentControlCuts && trustedReadOnlyCacheability,
            reportMaintenance = reportMaintenance, reportQuiescence = reportQuiescence))
        coherent.io.request <> io.request
        io.response <> coherent.io.response
        coherent.io.invalidate := io.invalidate
        io.invalidateDone.foreach(_ := coherent.io.invalidateDone.get)
        io.quiescent.foreach(_ := coherent.io.quiescent.get)
        coherent.io.quiescenceRequestPending.foreach(_ := io.quiescenceRequestPending.get)
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
    // Each phase has its own next equation: admission never enables unrelated
    // burst/response state registers through a shared FSM clock enable.
    val idle = RegInit(true.B)
    val lookup = RegInit(false.B)
    val send = RegInit(false.B)
    val receive = RegInit(false.B)
    val reply = RegInit(false.B)
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
    val ramClasses = if (p.cacheFetchPredecode) Some(WireDefault(I1InstructionPredecode.classify(ramWord))) else None
    // Read-only IF words use the spare eight bits of each 72-bit BRAM word.
    // Compute parcel length at refill, before the registered RAM write, so a
    // cache hit returns data and its classes together without another cycle.
    val packedInstruction = p.cacheFetchPredecode && allowHitReplacement
    if (packedInstruction) when(io.request.valid) { assert(!io.request.bits.write, "packed IF cache is read-only") }
    val ramWritePending = if (p.fpgaTimingCuts && bytes > 0) Some(RegInit(false.B)) else None
    val inWindow = if (p.fpgaTimingCuts)
        I1AddressWindow.contains(io.request.bits.address, p.cacheableBase, p.cacheableBytes)
        else io.request.bits.address >= p.cacheableBase.U &&
            io.request.bits.address < (p.cacheableBase + p.cacheableBytes).U
    val cacheable = (bytes > 0).B && (if (trustedReadOnlyCacheability) io.readCacheable.get
        else !io.request.bits.noAllocate && inWindow)
    io.response.valid := reply || (lookup && hit && !saved.write)
    io.response.bits := result
    io.response.bits.pageFault := false.B
    io.response.bits.fetchSpan := false.B
    // Hit qualifies VALID, not RAM data selection. Removing the tag compare
    // from this wide mux breaks tag -> data -> parcel decode scheduling.
    // A miss cannot consume this data because response.valid remains low.
    when(lookup && !saved.write) {
        io.response.bits.data := ramWord; io.response.bits.error := false.B
        io.response.bits.parcelClasses.foreach(_ := ramClasses.get)
    }
    io.request.ready := (if (allowHitReplacement)
        idle || (io.response.fire && !ramWritePending.getOrElse(false.B)) else idle)
    val tagLookup = lookup || writeLookupPending.getOrElse(false.B)
    io.hit := tagLookup && hit
    io.miss := tagLookup && !hit
    io.bypass := io.request.fire && !cacheable
    io.memory.request.valid := send
    io.memory.request.bits.address := Mux(savedCacheable && !saved.write,
        (saved.address >> lineBits) << lineBits, (saved.address >> offsetBits) << offsetBits)
    io.memory.request.bits.write := saved.write
    io.memory.request.bits.data := saved.data
    io.memory.request.bits.mask := saved.mask
    io.memory.request.bits.beats := Mux(savedCacheable && !saved.write, wordsPerLine.U, 1.U)
    io.memory.request.bits.size := Mux(savedCacheable && !saved.write, offsetBits.U, saved.size)
    io.memory.request.bits.byteOffset := Mux(savedCacheable && !saved.write, 0.U,
        saved.address(offsetBits - 1, 0))
    io.memory.response.ready := receive
    // Retention waits for the owner, deferred RAM write and upstream request.
    // Observation does not alter normal cache admission or response timing.
    io.quiescent.foreach(_ := idle && !ramWritePending.getOrElse(false.B) &&
        !writeLookupPending.getOrElse(false.B) && !io.quiescenceRequestPending.get)
    io.quiescenceRequestPending.foreach { pending =>
        when(!reset.asBool) {
            assert(!io.request.valid || pending, "cache quiescence bound omitted a live upstream offer")
        }
    }
    val accept = io.request.fire
    val needsLookup = if (p.overlapWriteLookup) cacheable && !io.request.bits.write else cacheable
    val lastBeatFire = io.memory.response.fire && io.memory.response.bits.last
    // A consumed hit/reply may replace the owner at this edge. The other
    // phases cannot admit a request, so their next equations stay local.
    idle := (idle || io.response.fire) && !accept
    lookup := accept && needsLookup
    send := (send && !io.memory.request.ready) || (accept && !needsLookup) ||
        (lookup && (!hit || saved.write))
    receive := (receive && !lastBeatFire) || (send && io.memory.request.ready)
    reply := (reply && !io.response.ready) ||
        (lookup && hit && !saved.write && !io.response.ready) || lastBeatFire
    // Burst bookkeeping is zero before entering receive, independent of the
    // next request admission path. A stalled receive keeps the current burst.
    when(!receive) { beat := 0.U; failed := false.B }
    // A free/completing local slot prepares payload before request VALID.
    // Active owners retain these fields through the response transfer; only
    // real acceptance advances the phase and validates the prepared payload.
    when(idle || io.response.fire) {
        saved := io.request.bits; savedCacheable := cacheable; writeHit := false.B
        fillKilled := io.invalidate
    }
    when(io.request.fire) {
        writeLookupPending.foreach(_ := cacheable && io.request.bits.write)
    }
    writeLookupPending.foreach { waiting =>
        // Tag RAM output belongs to the request accepted at the previous edge. Capture it ONCE,
        // even if the burst request is backpressured; later disabled RAM reads are unspecified.
        when(waiting) { writeHit := hit && !io.invalidate; waiting := false.B }
    }
    when(lookup) {
        when(hit && !saved.write) {
            when(!io.response.ready) {
                result.data := ramWord; result.error := false.B
                result.parcelClasses.foreach(_ := ramClasses.get)
            }
        }.otherwise { writeHit := hit && saved.write }
    }
    when(io.memory.response.fire) {
        failed := failed || io.memory.response.bits.error
        val desiredBeat = if (wordsPerLine == 1) 0.U else saved.address(lineBits - 1, offsetBits)
        when(!savedCacheable || saved.write || beat === desiredBeat) {
            result.data := io.memory.response.bits.data
            result.parcelClasses.foreach(_ := I1InstructionPredecode.classify(io.memory.response.bits.data))
        }
        when(io.memory.response.bits.last) {
            result.error := failed || io.memory.response.bits.error
        }.otherwise { beat := beat + 1.U }
    }
    when(io.invalidate && !idle) { fillKilled := true.B }
    if (bytes > 0) {
        val sets = bytes / p.cacheLineBytes
        val indexBits = log2Ceil(sets)
        // Every allocated line is inside the constant cacheable byte window.
        // Its common high prefix cannot distinguish two legal cached lines.
        // Keep all varying bits, including windows crossing a power-of-two boundary.
        val varyingAddressBits = if (p.fpgaTimingCuts)
            (p.cacheableBase ^ (p.cacheableBase + p.cacheableBytes - 1)).bitLength else p.xlen
        val tagBits = math.max(1, varyingAddressBits - lineBits - indexBits)
        val ramAddressBits = log2Ceil(bytes / (p.xlen / 8))
        val data = if (!packedInstruction) Some(SyncReadMem(bytes / (p.xlen / 8), Vec(p.xlen / 8, UInt(8.W)))) else None
        // Eight independent 4096x9 lanes use the BRAM byte/parity organization.
        // A monolithic 4096x72 memory is inferred as URAM with a slower output;
        // keeping byte lanes explicit preserves one-cycle IF latency and capacity.
        val instructionData = if (packedInstruction)
            Some(Seq.fill(8)(SyncReadMem(bytes / 8, UInt(9.W)))) else None
        val tags = if (!p.fpgaTimingCuts) Some(SyncReadMem(sets, UInt(tagBits.W))) else None
        val bankedTags = if (p.fpgaTimingCuts) Some(Module(new I1CacheTags(sets, tagBits))) else None
        chisel3.experimental.annotate(this)(Seq(firrtl.AttributeAnnotation(this.toNamed,
            "ram_style = \"block\"")))
        val valid = if (!p.fpgaTimingCuts) Some(RegInit(0.U(sets.W))) else None
        def set(address: UInt): UInt = address(lineBits + indexBits - 1, lineBits)
        def tag(address: UInt): UInt = if (varyingAddressBits <= lineBits + indexBits) 0.U(tagBits.W)
            else address(varyingAddressBits - 1, lineBits + indexBits)
        def word(address: UInt): UInt = address(ramAddressBits + offsetBits - 1, offsetBits)
        // Prefetch only through locally available ports, without hit -> READY
        // feedback. A real owner observes this read on its first lookup cycle;
        // stalled hits move data to result before the next prefetch can replace it.
        // Receive/install and delayed writes exclude all tag/data RAM collisions.
        val readEnable = if (p.fpgaTimingCuts) !receive && !ramWritePending.get
            else io.request.fire && cacheable
        if (packedInstruction) {
            val lanes = instructionData.get.map(_.read(word(io.request.bits.address), readEnable))
            ramWord := Cat(lanes.reverse.map(_(7, 0)))
            ramClasses.get := VecInit(lanes.map(_(8))).asUInt
        } else { ramWord := data.get.read(word(io.request.bits.address), readEnable).asUInt }
        val install = io.memory.response.fire && savedCacheable && !saved.write &&
            io.memory.response.bits.last && !failed && !io.memory.response.bits.error && !fillKilled && !io.invalidate
        val eraseSaved = (lookup && !hit && !saved.write) ||
            (io.memory.response.fire && saved.write && writeHit && io.memory.response.bits.error) ||
            (send && saved.write && saved.noAllocate)
        bankedTags.foreach { bank =>
            bank.io.readValid := readEnable
            bank.io.readSet := set(io.request.bits.address)
            // Tags capture their comparison on the same prefetch edge as data/presence.
            bank.io.expectedTag := tag(io.request.bits.address)
            bank.io.writeValid := install
            bank.io.writeSet := set(saved.address)
            bank.io.writeTag := tag(saved.address)
            // A bypass write owns this cache exclusively through its real
            // reply. Erase its saved row in send, before external bytes change;
            // admission's live translation/address never drives the valid bank.
            bank.io.eraseValid := eraseSaved
            bank.io.eraseSet := set(saved.address)
            bank.io.invalidate := io.invalidate
        }
        val tagMatch = bankedTags.map(_.io.matches).getOrElse(
            tags.get.read(set(io.request.bits.address), readEnable) === tag(saved.address))
        // Tag, data and presence describe the same prefetched address. Only
        // accepted owners use them; invalidation also cancels the current lookup.
        val present = valid.map(_(set(saved.address))).getOrElse(true.B)
        hit := present && tagMatch && !io.invalidate
        val fill = io.memory.response.fire && savedCacheable && !saved.write
        val update = io.memory.response.fire && saved.write && writeHit && !io.memory.response.bits.error
        val fillWord = (word(saved.address) >> log2Ceil(wordsPerLine)) << log2Ceil(wordsPerLine) | beat
        val writeData = Mux(update, saved.data, io.memory.response.bits.data)
        val writePayload = if (packedInstruction) Cat(I1InstructionPredecode.classify(writeData), writeData) else writeData
        val mask = Mux(update, saved.mask, ((BigInt(1) << (p.xlen / 8)) - 1).U)
        val writeAddress = Mux(update, word(saved.address), fillWord)
        if (p.fpgaTimingCuts) {
            // One beat of RAM-write scheduling, NOT another transaction owner.
            // Consecutive refill beats still write one per cycle. Last-beat hit
            // replacement is held until the scheduled write is drained, avoiding
            // undefined same-address read/write data without relying on vendor mode.
            val heldData = RegEnable(writePayload, fill || update)
            val heldMask = RegEnable(mask, fill || update)
            val heldAddress = RegEnable(writeAddress, fill || update)
            ramWritePending.get := fill || update
            when(ramWritePending.get) {
                if (packedInstruction) for ((lane, i) <- instructionData.get.zipWithIndex) {
                    lane.write(heldAddress, Cat(heldData(64 + i), heldData(8 * i + 7, 8 * i)))
                }
                else data.get.write(heldAddress, heldData.asTypeOf(Vec(p.xlen / 8, UInt(8.W))), heldMask.asBools)
            }
        } else when(fill || update) {
            if (packedInstruction) for ((lane, i) <- instructionData.get.zipWithIndex) {
                lane.write(writeAddress, Cat(writePayload(64 + i), writePayload(8 * i + 7, 8 * i)))
            }
            else data.get.write(writeAddress, writeData.asTypeOf(Vec(p.xlen / 8, UInt(8.W))), mask.asBools)
        }
        tags.foreach { memory => when(install) { memory.write(set(saved.address), tag(saved.address)) } }
        valid.foreach { bits =>
            when(install) { bits := bits | UIntToOH(set(saved.address), sets) }
            // Never publish an old tag after a failed refill or write error.
            when(lookup && !hit && !saved.write ||
                io.memory.response.fire && saved.write && writeHit && io.memory.response.bits.error) {
                bits := bits & ~UIntToOH(set(saved.address), sets)
            }
            when(io.request.fire && io.request.bits.write && io.request.bits.noAllocate) {
                bits := bits & ~UIntToOH(set(io.request.bits.address), sets)
            }
            when(io.invalidate) { bits := 0.U }
        }
    }
    when(!reset.asBool) {
        if (trustedReadOnlyCacheability) when(io.request.fire) {
            assert(!io.request.bits.write && !io.request.bits.atomic, "trusted IF cache port must remain read-only")
            assert(io.readCacheable.get === (!io.request.bits.noAllocate && inWindow),
                "trusted IF cacheability contradicts physical/noAllocate policy")
        }
        assert(!io.request.fire || !io.request.bits.atomic, "raw atomic reached cache without physical atomic owner")
        assert(!io.memory.response.valid || receive, "cache received an unowned burst response")
        when(io.memory.response.fire) {
            val expectedLast = !savedCacheable || saved.write || beat === (wordsPerLine - 1).U
            assert(io.memory.response.bits.last === expectedLast, "cache burst length/last mismatch")
        }
    }
    }
    // Physical caches/atomic memory and the host-only walker never create guest faults.
    io.response.bits.guest.foreach(_ := 0.U.asTypeOf(new I1GuestFault))

}
