package soc.core.ooo

import chisel3._
import chisel3.util._

class SvTranslationRequest extends Bundle {
    val virtualAddress = UInt(64.W)
    val rootPpn        = UInt(44.W)
    val asid           = UInt(16.W)
    val mode           = UInt(4.W)
    val privilege      = UInt(2.W)
    val access         = UInt(2.W)
    val sum            = Bool()
    val mxr            = Bool()
}

class SvTranslationResponse extends SvWalkResponse

/** Client is the master: each accepted request has one response. TLB hits may respond in the request cycle. */
class SvTranslationPort extends Bundle {
    val request  = Decoupled(new SvTranslationRequest)
    val response = Flipped(Decoupled(new SvTranslationResponse))
}

private[ooo] class SvTlbEntry extends Bundle {
    val valid     = Bool()
    val request   = new SvTranslationRequest
    val response  = new SvTranslationResponse
}

object SvTranslationService {
    val DefaultEntries = 8
    val SupportedEntries: Set[Int] = Set(4, 8, 16, 32)

    // Exact powers of two make a wrapping replacement index address every entry,
    // without an unreachable slot or a truncation/modulo mismatch at 32 entries.
    def indexBits(entries: Int): Int = {
        require(SupportedEntries.contains(entries) && entries > 0 && (entries & (entries - 1)) == 0,
            "translation entries must be 4, 8, 16 or 32")
        Integer.numberOfTrailingZeros(entries)
    }
}

/** A bounded 4/8/16/32-entry parallel-lookup TLB backed by a parameterized page walker. The key includes access and effective
  * privilege. Optional successful-write data permission subsumption never grants writes from a read or execution
  * from data access. Superpage hits reconstruct the new VA offset. I/D walkers can miss concurrently.
  */
class SvTranslationService(val maxLevels: Int = 4, val entries: Int = 8, pmpEntries: Int = 16,
    val loadPeek: Boolean = false, val writeReadReuse: Boolean = false, val missCacheEntries: Int = 0) extends Module {
    require(Set(0, 32, 64, 128).contains(missCacheEntries),
        "miss cache entries must be 0, 32, 64 or 128 (two ways)")
    private val enableLoadPeek = loadPeek
    require(Set(3, 4, 5).contains(maxLevels))
    private val entryIndexBits = SvTranslationService.indexBits(entries)
    val io = IO(new Bundle {
        val client    = Flipped(new SvTranslationPort)
        val loadPeek = if (enableLoadPeek) Some(Flipped(new SvTranslationPeekPort)) else None
        val flush     = Input(Bool())
        val idle      = Output(Bool())
        val pmpState  = Input(new PmpState)
        val memory    = new SvPteReadPort
        val tlbHit    = Output(Bool())
        val walkStart = Output(Bool())
        val pteRead   = Output(Bool())
    })
    val walker = Module(new SvPageTableWalker(maxLevels, pmpEntries))
    walker.io.pmpState := io.pmpState
    io.memory <> walker.io.memory
    val tlb  = RegInit(VecInit(Seq.fill(entries)(0.U.asTypeOf(new SvTlbEntry))))
    val next = RegInit(0.U(entryIndexBits.W))
    val states = Enum(if (missCacheEntries > 0) 5 else 3)
    val idle = states(0)
    val walking = states(1)
    val replying = states(2)
    val state = RegInit(idle)
    val saved = Reg(new SvTranslationRequest)
    val savedResponse = Reg(new SvTranslationResponse)
    val request = io.client.request.bits
    val activeMode = request.mode =/= 0.U && request.privilege =/= 3.U
    // No new permission state: successful Svade WRITE/RW already proves
    // R=1, W=1, A=1, D=1 (W without R is an invalid PTE). In exactly the
    // same root/ASID/mode/privilege/SUM/MXR context it can cover data R/W/RW,
    // never execute. A read (including MXR) cannot authorize a write.
    // Final data PMP checks and SFENCE/drain contracts are unchanged.
    def samePage(entry: SvTlbEntry, query: SvTranslationRequest): Bool = {
            val prior = entry.request
            val topMatches = MuxLookup(query.mode, false.B)(Seq(
                8.U -> (prior.virtualAddress(63, 39) === query.virtualAddress(63, 39)),
                9.U -> (prior.virtualAddress(63, 48) === query.virtualAddress(63, 48)),
                10.U -> (prior.virtualAddress(63, 57) === query.virtualAddress(63, 57))
            ))
            val contextMatches = prior.rootPpn === query.rootPpn && prior.asid === query.asid &&
                prior.mode === query.mode && prior.privilege === query.privilege &&
                prior.sum === query.sum && prior.mxr === query.mxr && topMatches
            val level = entry.response.level
            val matchingVpn = (0 until maxLevels).map { j =>
                level > j.U || (if (j == 0) entry.response.napot &&
                    query.virtualAddress(20, 16) === prior.virtualAddress(20, 16) else false.B) ||
                    query.virtualAddress(12 + 9 * j + 8, 12 + 9 * j) ===
                        prior.virtualAddress(12 + 9 * j + 8, 12 + 9 * j)
            }.reduce(_ && _)
            entry.valid && contextMatches && matchingVpn
    }
    // Demand and optional access-qualified peek use the same permissions and
    // superpage/NAPOT reconstruction. Peek never starts walks or replacements.
    def lookup(query: SvTranslationRequest): (Bool, SvTranslationResponse) = {
        val hits = Wire(Vec(entries, Bool()))
        for (i <- 0 until entries) {
            val prior = tlb(i).request
            val priorWrite = prior.access === PmpAccess.write || prior.access === PmpAccess.readWrite
            val dataAccess = query.access === PmpAccess.read || query.access === PmpAccess.write ||
                query.access === PmpAccess.readWrite
            val accessMatches = prior.access === query.access ||
                (if (writeReadReuse) priorWrite && dataAccess else false.B)
            hits(i) := samePage(tlb(i), query) && accessMatches
        }
        val cached = tlb(PriorityEncoder(hits))
        val offsetMasks = (0 until maxLevels).map(i => i.U -> ((BigInt(1) << (12 + 9 * i)) - 1).U(64.W))
        val offsetMask = Mux(cached.response.napot, "hffff".U(64.W),
            MuxLookup(cached.response.level, offsetMasks.head._2)(offsetMasks))
        val response = WireDefault(cached.response)
        response.physicalAddress := (cached.response.physicalAddress & ~offsetMask) |
            (query.virtualAddress & offsetMask)
        (query.mode =/= 0.U && query.privilege =/= 3.U && hits.asUInt.orR, response)
    }
    // Opt-in miss-only inclusive cache. Its synchronous memory and comparator are
    // absent from both original demand-hit and hit-only peek lookup cones.
    val missCacheFill = WireDefault(false.B)
    val missCacheResponse = WireDefault(0.U.asTypeOf(new SvTranslationResponse))
    val missCacheProbe = WireDefault(false.B)
    val (hit, cachedResponse) = lookup(request)
    val fast = !activeMode || hit
    val fastResponse = WireDefault(0.U.asTypeOf(new SvTranslationResponse))
    fastResponse.physicalAddress := Mux(activeMode, cachedResponse.physicalAddress, request.virtualAddress)
    fastResponse.level := Mux(activeMode, cachedResponse.level, 0.U)
    fastResponse.napot := activeMode && cachedResponse.napot
    fastResponse.global := activeMode && cachedResponse.global
    fastResponse.pbmt := Mux(activeMode, cachedResponse.pbmt, 0.U)

    io.loadPeek.foreach { peek =>
        val (peekHit, response) = lookup(peek.request.bits)
        peek.response.valid := peek.request.valid && peekHit && !io.flush &&
            (peek.request.bits.access === PmpAccess.read || peek.request.bits.access === PmpAccess.write) &&
            !response.pageFault && !response.accessFault
        peek.response.bits := response
    }

    io.client.response.valid := (state === idle && io.client.request.valid && fast && !io.flush) ||
        state === replying
    io.client.response.bits := Mux(state === replying, savedResponse, fastResponse)
    io.client.request.ready := state === idle && !io.flush && Mux(fast, io.client.response.ready, true.B)
    io.tlbHit := state === idle && io.client.request.fire && hit
    io.idle := state === idle && !walker.io.complete.valid
    when(io.client.request.fire && !fast) {
        saved := request
        state := Mux(missCacheProbe, states.last, walking)
    }
    walker.io.start.valid := state === walking
    walker.io.start.bits.virtualAddress := saved.virtualAddress
    walker.io.start.bits.rootPpn := saved.rootPpn
    walker.io.start.bits.mode := saved.mode
    walker.io.start.bits.privilege := saved.privilege
    walker.io.start.bits.access := saved.access
    walker.io.start.bits.sum := saved.sum
    walker.io.start.bits.mxr := saved.mxr
    io.walkStart := walker.io.start.fire
    io.pteRead := walker.io.memory.request.fire
    walker.io.complete.ready := state === walking
    if (missCacheEntries > 0) {
        val probe0 = states(4)
        val probe1 = states(3)
        val sets = missCacheEntries / 2
        val setBits = log2Ceil(sets)
        val cache = SyncReadMem(missCacheEntries, new SvTlbEntry)
        val valid = RegInit(VecInit(Seq.fill(missCacheEntries)(false.B)))
        val victim = RegInit(VecInit(Seq.fill(sets)(false.B)))
        val firstHit = RegInit(false.B)
        val firstMatch = RegInit(false.B)
        val firstResponse = Reg(new SvTranslationResponse)
        val fillIndex = Reg(UInt((setBits + 1).W))
        val group = saved.virtualAddress(11 + setBits, 12)
        val firstIndex = Cat(false.B, group)
        val secondIndex = Cat(true.B, group)
        missCacheProbe := request.mode === 8.U && request.privilege =/= 3.U
        val launch = io.client.request.fire && !fast && missCacheProbe
        val readEnable = launch || state === probe0
        val readIndex = Mux(launch, Cat(false.B, request.virtualAddress(11 + setBits, 12)), secondIndex)
        val row = cache.read(readIndex, readEnable)
        val candidate = WireDefault(row)
        candidate.valid := Mux(state === probe0, valid(firstIndex), valid(secondIndex))
        val matches = samePage(candidate, saved)
        val priorWrite = candidate.request.access === PmpAccess.write ||
            candidate.request.access === PmpAccess.readWrite
        val dataAccess = saved.access === PmpAccess.read || saved.access === PmpAccess.write ||
            saved.access === PmpAccess.readWrite
        val allowed = candidate.request.access === saved.access ||
            (if (writeReadReuse) priorWrite && dataAccess else false.B)
        val found = matches && allowed
        val response = WireDefault(candidate.response)
        response.physicalAddress := Cat(candidate.response.physicalAddress(63, 12), saved.virtualAddress(11, 0))
        when(state === probe0) {
            firstHit := found
            firstMatch := matches
            firstResponse := response
            state := probe1
        }
        when(state === probe1) {
            val selected = Mux(firstMatch, firstIndex, Mux(matches, secondIndex,
                Mux(!valid(firstIndex), firstIndex, Mux(!valid(secondIndex), secondIndex,
                    Cat(victim(group), group)))))
            fillIndex := selected
            when(firstHit || found) {
                missCacheFill := true.B
                missCacheResponse := Mux(firstHit, firstResponse, response)
                savedResponse := missCacheResponse
                state := replying
            }.otherwise { state := walking }
        }
        when(walker.io.complete.fire && !walker.io.complete.bits.pageFault &&
            !walker.io.complete.bits.accessFault && saved.mode === 8.U &&
            walker.io.complete.bits.level === 0.U && !walker.io.complete.bits.napot) {
            val entry = Wire(new SvTlbEntry)
            entry.valid := true.B
            entry.request := saved
            entry.response := walker.io.complete.bits
            assert(!readEnable, "miss-cache synchronous read and write cannot overlap")
            cache.write(fillIndex, entry)
            valid(fillIndex) := true.B
            victim(group) := !fillIndex(setBits)
        }
        when(io.flush) {
            for (i <- 0 until missCacheEntries) { valid(i) := false.B }
        }
    }
    when(walker.io.complete.fire) {
        savedResponse := walker.io.complete.bits
        state := replying
    }
    val fillResponse = Wire(new SvTranslationResponse)
    fillResponse := walker.io.complete.bits
    when(missCacheFill) { fillResponse := missCacheResponse }
    assert(!(walker.io.complete.fire && missCacheFill), "PTW and miss-cache cannot reply to one request together")
    when(walker.io.complete.fire || missCacheFill) {
        when(!fillResponse.pageFault && !fillResponse.accessFault) {
            // Upgrade the already matching read entry after a successful
            // write walk instead of consuming a second entry for that page.
            // Failed walks never insert/upgrade. Only the exact saved context
            // participates; no PTE permission is inferred from a read.
            val matching = VecInit(tlb.map(e => samePage(e, saved)))
            val reuse = (if (writeReadReuse) matching.asUInt.orR else false.B)
            val insert = Mux(reuse, PriorityEncoder(matching), next)
            tlb(insert).valid := true.B
            tlb(insert).request := saved
            tlb(insert).response := fillResponse
            when(!reuse) { next := next + 1.U }
            if (writeReadReuse) {
                for (i <- 0 until entries) {
                    when(reuse && matching(i) && insert =/= i.U) { tlb(i).valid := false.B }
                }
            }
        }
    }
    when(io.client.response.fire && state === replying) { state := idle }
    when(io.flush) {
        assert(state === idle, "translation flush requires drained requests")
        for (i <- 0 until entries) { tlb(i).valid := false.B }
    }
}

private[ooo] class SvCachedNonLeaf extends Bundle {
    val valid   = Bool()
    val address = UInt(64.W)
    val data    = UInt(64.W)
}

/** One PTE read is converted to the ordered physical data port. Valid non-leaf PTEs can be reused after the
  * walker has performed its PMP check. The owner must flush this cache with the TLB after SFENCE.VMA.
  */
class SvPteDataBridge(entries: Int = 8) extends Module {
    require(Set(4, 8, 16).contains(entries))
    val io = IO(new Bundle {
        val walk = Flipped(new SvPteReadPort)
        val data = new DataPort
        val flush = Input(Bool())
        val idle = Output(Bool())
        val cacheHit = Output(Bool())
        val physicalRead = Output(Bool())
    })
    val idle :: waiting :: cachedReply :: Nil = Enum(3)
    val state = RegInit(idle)
    val cache = RegInit(VecInit(Seq.fill(entries)(0.U.asTypeOf(new SvCachedNonLeaf))))
    val next = RegInit(0.U(log2Ceil(entries).W))
    val pendingAddress = Reg(UInt(64.W))
    val cachedData = Reg(UInt(64.W))
    val matches = VecInit(cache.map(e => e.valid && e.address === io.walk.request.bits))
    val hit = matches.asUInt.orR

    io.idle := state === idle
    io.walk.request.ready := state === idle && !io.flush && Mux(hit, true.B, io.data.request.ready)
    io.data.request.valid := state === idle && !io.flush && io.walk.request.valid && !hit
    io.data.request.bits := 0.U.asTypeOf(new DataRequest)
    io.data.request.bits.address := io.walk.request.bits
    io.data.request.bits.size := 3.U
    io.data.request.bits.mask := 255.U
    io.cacheHit := io.walk.request.fire && hit
    io.physicalRead := io.data.request.fire
    io.data.response.ready := state === waiting && io.walk.response.ready
    io.walk.response.valid := state === cachedReply || (state === waiting && io.data.response.valid)
    io.walk.response.bits.data := Mux(state === cachedReply, cachedData, io.data.response.bits.data)
    io.walk.response.bits.error := state === waiting && io.data.response.bits.error

    when(io.walk.request.fire) {
        when(hit) {
            cachedData := cache(PriorityEncoder(matches)).data
            state := cachedReply
        }.otherwise {
            pendingAddress := io.walk.request.bits
            state := waiting
        }
    }
    when(io.walk.response.fire) {
        state := idle
        val pte = io.data.response.bits.data
        val validNonLeaf = pte(0) && !pte(3, 1).orR && !pte(4) && !pte(7, 6).orR &&
            !pte(63, 54).orR
        when(state === waiting && !io.data.response.bits.error && validNonLeaf) {
            cache(next).valid := true.B
            cache(next).address := pendingAddress
            cache(next).data := pte
            next := next + 1.U
        }
    }
    when(io.flush) {
        assert(state === idle, "page-walk cache flush requires drained reads")
        for (i <- 0 until entries) { cache(i).valid := false.B }
    }
}
