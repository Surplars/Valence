package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.ip.tilelink.TileLinkLineFillEngine

/** Two-way, SRAM-backed instruction cache for executable RAM. A whole-line Get is only used when the requested
  * packet and all 64 bytes of its line are executable under the current PMP state. ROM, partial packets and PMP
  * boundaries retain the precise word-level behavior of InstructionTileLinkBridge.
  */
class InstructionLineCache(
    params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
    ramBase: BigInt = BigInt("80010000", 16),
    ramBytes: BigInt = 4096,
    romBytes: Int = 8192,
    lines: Int = 16,
    packetWords: Int = 2,
    prefetchEnabled: Boolean = false,
    parallelFallbackAddresses: Boolean = false,
    tagConfig: CacheTagConfig = CacheTagConfig.FullWidth
) extends Module {
    require(lines >= 4 && lines <= 512 && isPow2(lines))
    require(ramBase >= 0 && ramBase % 64 == 0 && ramBytes >= 64 && ramBytes % 64 == 0)
    require(ramBase + ramBytes <= (BigInt(1) << 64))
    require(params.addrWidth == 64 && params.dataWidth == 64 && params.sourceBits >= 3)
    require(Set(2, 4).contains(packetWords))
    private val sets = lines / 2
    private val prefetchSlots = 2
    private val indexBits = log2Ceil(sets)
    private val tagGeometry = tagConfig.geometry(ramBase, ramBytes, 6 + indexBits)
    private val tagBits = tagGeometry.tagBits
    val io = IO(new Bundle {
        val fetch = Flipped(new InstructionPort(packetWords))
        val tl = new TLBundle(params)
        val pmpState = Input(new PmpState)
        val privilege = Input(UInt(2.W))
        val invalidate = Input(Bool())
        val idle = Output(Bool())
    })

    private val fallback = Module(new InstructionTileLinkBridge(params, immutableBytes = romBytes,
        parallelAddresses = parallelFallbackAddresses))
    private val wideFallback = if (packetWords == 4) Some(Module(new WideInstructionAdapter)) else None
    wideFallback.foreach(_.io.narrow <> fallback.io.fetch)
    private val fallbackFetch = wideFallback.map(_.io.wide).getOrElse(fallback.io.fetch)
    private val fill = Module(new TileLinkLineFillEngine(params, entries = 4, tagBits = 2))
    private val Seq(idle, fallbackActive, sendFill, waitFill, waitPrefetch, hitReply, lineReply,
        retryFallback) = Enum(8)
    private val state = RegInit(idle)
    private val valid = RegInit(VecInit(Seq.fill(sets)(VecInit(Seq.fill(2)(false.B)))))
    private val tags = Reg(Vec(sets, Vec(2, UInt(tagBits.W))))
    private val replace = RegInit(VecInit(Seq.fill(sets)(false.B)))
    private val data = Seq.fill(2)(SyncReadMem(sets, UInt(512.W)))
    private val savedPc = Reg(UInt(64.W))
    private val savedMask = Reg(UInt(packetWords.W))
    private val savedLine = Reg(UInt(64.W))
    private val savedSet = Reg(UInt(indexBits.W))
    private val savedTag = Reg(UInt(tagBits.W))
    private val savedWay = Reg(Bool())
    private val savedOffset = Reg(UInt(3.W))
    private val replyData = Reg(UInt((packetWords * 32).W))
    private val staleFill = RegInit(false.B)
    private val prefetchCandidate = RegInit(false.B)
    private val prefetchCandidateLine = Reg(UInt(64.W))
    private val prefetchOutstanding = RegInit(VecInit(Seq.fill(prefetchSlots)(false.B)))
    private val prefetchLine = Reg(Vec(prefetchSlots, UInt(64.W)))
    private val prefetchStale = RegInit(VecInit(Seq.fill(prefetchSlots)(false.B)))
    private val lastDemandLine = Reg(UInt(64.W))

    private val requestPc = io.fetch.request.bits
    private val requestLine = Cat(requestPc(63, 6), 0.U(6.W))
    private val requestSet = requestPc(5 + indexBits, 6)
    private val requestTag = tagGeometry.tag(requestPc)
    private val inRam = requestLine >= ramBase.U &&
        (requestLine +& 63.U) < (ramBase + ramBytes).U(65.W)
    private val pmp = Module(new PmpChecker(16))
    pmp.io.state := io.pmpState
    pmp.io.address := requestLine
    pmp.io.size := 6.U
    pmp.io.privilege := io.privilege
    pmp.io.access := PmpAccess.execute
    // This physical cache can serve sixteen-byte packets at eight-byte granularity.
    // Every offset 0..48 fits in one 64-byte line; only offset 56 needs precise fallback.
    // savedOffset already selects either hit SRAM data or the filled line at eight-byte granularity.
    private val packetFitsLine = if (packetWords == 4) requestPc(5, 3) =/= 7.U else true.B
    private val lineAllowed = inRam && requestPc(2, 0) === 0.U && packetFitsLine &&
        io.fetch.requestMask === ((1 << packetWords) - 1).U && !pmp.io.denied
    private val hits = VecInit((0 until 2).map { way =>
        tagGeometry.qualifies(requestPc) && valid(requestSet)(way) && tags(requestSet)(way) === requestTag && !io.invalidate
    })
    private val hit = hits.asUInt.orR
    private val hitWay = hits(1)
    private val victim = Mux(!valid(requestSet)(0), false.B,
        Mux(!valid(requestSet)(1), true.B, replace(requestSet)))
    private val prefetchedPending = (0 until prefetchSlots).map(i =>
        prefetchOutstanding(i) && !prefetchStale(i) &&
            prefetchLine(i) === requestLine).reduce(_ || _) && !io.invalidate
    private val nextLine = requestLine + 64.U
    private val nextSet = nextLine(5 + indexBits, 6)
    private val nextTag = tagGeometry.tag(nextLine)
    private val nextCached = (0 until 2).map(way =>
        tagGeometry.qualifies(nextLine) && valid(nextSet)(way) && tags(nextSet)(way) === nextTag).reduce(_ || _)
    private val nextPending = (0 until prefetchSlots).map(i =>
        prefetchOutstanding(i) && prefetchLine(i) === nextLine).reduce(_ || _)
    private val prefetchPmp = Module(new PmpChecker(16))
    prefetchPmp.io.state := io.pmpState
    prefetchPmp.io.address := nextLine
    prefetchPmp.io.size := 6.U
    prefetchPmp.io.privilege := io.privilege
    prefetchPmp.io.access := PmpAccess.execute
    private val nextExecutable = requestLine(11, 6) =/= 63.U &&
        nextLine >= ramBase.U && (nextLine +& 63.U) < (ramBase + ramBytes).U(65.W) &&
        !prefetchPmp.io.denied && !nextCached
    private val followingLine = prefetchCandidateLine + 64.U
    private val followingSet = followingLine(5 + indexBits, 6)
    private val followingTag = tagGeometry.tag(followingLine)
    private val followingCached = (0 until 2).map(way =>
        tagGeometry.qualifies(followingLine) && valid(followingSet)(way) && tags(followingSet)(way) === followingTag).reduce(_ || _)
    private val followingPending = (0 until prefetchSlots).map(i =>
        prefetchOutstanding(i) && prefetchLine(i) === followingLine).reduce(_ || _)
    private val prefetchDistance = math.min(4, sets - 1)
    private val followingPmp = Module(new PmpChecker(16))
    followingPmp.io.state := io.pmpState
    followingPmp.io.address := followingLine
    followingPmp.io.size := 6.U
    followingPmp.io.privilege := io.privilege
    followingPmp.io.access := PmpAccess.execute
    private val followingExecutable = prefetchCandidateLine(11, 6) =/= 63.U &&
        followingLine >= ramBase.U &&
        (followingLine +& 63.U) < (ramBase + ramBytes).U(65.W) &&
        !followingPmp.io.denied && !followingCached
    private val responsePrefetchSlot = (fill.io.response.bits.tag - 1.U)(0)
    private val responsePrefetchLine = prefetchLine(responsePrefetchSlot)
    private val prefetchSet = responsePrefetchLine(5 + indexBits, 6)
    private val prefetchTag = tagGeometry.tag(responsePrefetchLine)
    private val prefetchVictim = Mux(!valid(prefetchSet)(0), false.B,
        Mux(!valid(prefetchSet)(1), true.B, replace(prefetchSet)))
    private val candidatePmp = Module(new PmpChecker(16))
    candidatePmp.io.state := io.pmpState
    candidatePmp.io.address := prefetchCandidateLine
    candidatePmp.io.size := 6.U
    candidatePmp.io.privilege := io.privilege
    candidatePmp.io.access := PmpAccess.execute

    // The synchronous SRAM delivers the previous hit while its port accepts the next read.
    // A line-fill reply can also hand the port to the following request without a bubble.
    val acceptWindow = state === idle ||
        ((state === hitReply || state === lineReply) && io.fetch.response.ready)
    val prefetchReply = fill.io.response.valid && fill.io.response.bits.tag =/= 0.U
    io.idle := state === idle && !prefetchCandidate && !prefetchOutstanding.asUInt.orR
    io.fetch.request.ready := acceptWindow &&
        Mux(lineAllowed, true.B, fallbackFetch.request.ready) &&
        !prefetchReply
    fallbackFetch.request.valid := state === retryFallback ||
        (acceptWindow && io.fetch.request.valid && !lineAllowed && !prefetchReply)
    fallbackFetch.request.bits := Mux(state === retryFallback, savedPc, requestPc)
    fallbackFetch.requestMask := Mux(state === retryFallback, savedMask, io.fetch.requestMask)
    fallbackFetch.response.ready := state === fallbackActive && io.fetch.response.ready

    val readWords = VecInit((0 until 2).map { way =>
        data(way).read(requestSet, io.fetch.request.fire && lineAllowed && hits(way))
    })
    val hitData = Mux(savedWay, readWords(1), readWords(0))
    val hitPacket = (hitData >> (savedOffset << 6))(packetWords * 32 - 1, 0)
    io.fetch.response.valid := state === hitReply || state === lineReply ||
        (state === fallbackActive && fallbackFetch.response.valid)
    io.fetch.response.bits := Mux(state === hitReply, hitPacket,
        Mux(state === lineReply, replyData, fallbackFetch.response.bits))
    io.fetch.responseError := Mux(state === fallbackActive, fallbackFetch.responseError, 0.U)
    io.fetch.responsePageFault := Mux(state === fallbackActive, fallbackFetch.responsePageFault, 0.U)

    when(io.invalidate) {
        for (set <- 0 until sets; way <- 0 until 2) { valid(set)(way) := false.B }
        when(state === sendFill || state === waitFill) { staleFill := true.B }
        prefetchCandidate := false.B
        for (slot <- 0 until prefetchSlots) {
            when(prefetchOutstanding(slot)) { prefetchStale(slot) := true.B }
        }
    }
    when((state === hitReply || state === lineReply || state === fallbackActive) &&
        io.fetch.response.fire && !io.fetch.request.fire) {
        state := idle
    }
    when(io.fetch.request.fire) {
        when(prefetchCandidate && requestLine === prefetchCandidateLine) {
            prefetchCandidate := false.B
        }
        when(lineAllowed) {
            lastDemandLine := requestLine
            savedPc := requestPc
            savedMask := io.fetch.requestMask
            savedLine := requestLine
            savedSet := requestSet
            savedTag := requestTag
            savedWay := Mux(hit, hitWay, victim)
            savedOffset := requestPc(5, 3)
            when(hit) {
                replace(requestSet) := !hitWay
                state := hitReply
            }.elsewhen(prefetchedPending) {
                state := waitPrefetch
            }.otherwise {
                staleFill := io.invalidate
                state := sendFill
            }
            if (prefetchEnabled) {
                when((!hit || requestPc(5, 4) === 3.U) &&
                    nextExecutable && !nextPending && !prefetchCandidate) {
                    prefetchCandidate := true.B
                    prefetchCandidateLine := nextLine
                }
            }
        }.otherwise { state := fallbackActive }
        for (slot <- 0 until prefetchSlots) {
            val ahead = (0 to prefetchDistance).map(distance =>
                requestLine + (distance * 64).U === prefetchLine(slot)).reduce(_ || _)
            when(prefetchOutstanding(slot) && !ahead) { prefetchStale(slot) := true.B }
        }
    }
    val demandFill = state === sendFill
    val freePrefetch = VecInit((0 until prefetchSlots).map(i => !prefetchOutstanding(i)))
    val prefetchSlot = PriorityEncoder(freePrefetch)
    when(prefetchCandidate && candidatePmp.io.denied) { prefetchCandidate := false.B }
    fill.io.request.valid := demandFill || (prefetchCandidate && !io.invalidate &&
        freePrefetch.asUInt.orR && !candidatePmp.io.denied &&
        !(acceptWindow && io.fetch.request.valid && requestLine === prefetchCandidateLine))
    fill.io.request.bits.address := Mux(demandFill, savedLine, prefetchCandidateLine)
    fill.io.request.bits.tag := Mux(demandFill, 0.U(2.W),
        Mux(prefetchSlot === 0.U, 1.U(2.W), 2.U(2.W)))
    when(fill.io.request.fire) {
        when(demandFill) { state := waitFill }
        .otherwise {
            prefetchCandidate := false.B
            prefetchOutstanding(prefetchSlot) := true.B
            prefetchLine(prefetchSlot) := prefetchCandidateLine
            prefetchStale(prefetchSlot) := false.B
            if (prefetchEnabled) {
                val frontier = Mux(io.fetch.request.fire && lineAllowed, requestLine, lastDemandLine)
                when(followingExecutable && !followingPending &&
                    prefetchCandidateLine < frontier + (prefetchDistance * 64).U) {
                    prefetchCandidate := true.B
                    prefetchCandidateLine := followingLine
                }
            }
        }
    }
    fill.io.response.ready := Mux(fill.io.response.bits.tag === 0.U,
        state === waitFill, prefetchOutstanding(responsePrefetchSlot))
    val prefetchWrite = fill.io.response.fire && fill.io.response.bits.tag =/= 0.U &&
        !prefetchStale(responsePrefetchSlot) && !io.invalidate && !fill.io.response.bits.error
    val demandWrite = fill.io.response.fire && fill.io.response.bits.tag === 0.U &&
        !fill.io.response.bits.error && !staleFill && !io.invalidate
    for (way <- 0 until 2) {
        when((prefetchWrite && prefetchVictim === (way == 1).B) ||
            (demandWrite && savedWay === (way == 1).B)) {
            data(way).write(Mux(prefetchWrite, prefetchSet, savedSet), fill.io.response.bits.data)
        }
    }
    when(fill.io.response.fire) {
        when(fill.io.response.bits.tag =/= 0.U) {
            prefetchOutstanding(responsePrefetchSlot) := false.B
            when(!prefetchStale(responsePrefetchSlot) && !io.invalidate &&
                !fill.io.response.bits.error) {
                if (tagConfig.compact) assert(tagGeometry.contains(responsePrefetchLine), "prefetch tag outside aperture")
                tags(prefetchSet)(prefetchVictim.asUInt) := prefetchTag
                valid(prefetchSet)(prefetchVictim.asUInt) := true.B
                replace(prefetchSet) := !prefetchVictim
            }
            when(state === waitPrefetch && savedLine === responsePrefetchLine) {
                when(fill.io.response.bits.error) { state := retryFallback }
                .otherwise {
                    replyData := (fill.io.response.bits.data >> (savedOffset << 6))(
                        packetWords * 32 - 1, 0)
                    state := lineReply
                }
            }
        }.elsewhen(fill.io.response.bits.error) {
            // A line fault must not turn a successful requested word into a fault.
            // Retry only the original packet for precise per-word error reporting.
            state := retryFallback
        }.otherwise {
            when(!staleFill && !io.invalidate) {
                if (tagConfig.compact) assert(tagGeometry.contains(savedLine), "instruction tag outside aperture")
                tags(savedSet)(savedWay.asUInt) := savedTag
                valid(savedSet)(savedWay.asUInt) := true.B
                replace(savedSet) := !savedWay
            }
            replyData := (fill.io.response.bits.data >> (savedOffset << 6))(packetWords * 32 - 1, 0)
            state := lineReply
        }
    }
    // Passive test accessors: no production ports, counters, or control-path changes.
    val perfAcceptedHit: Bool = io.fetch.request.fire && lineAllowed && hit
    val perfAcceptedMiss: Bool = io.fetch.request.fire && lineAllowed && !hit
    val perfAcceptedFallback: Bool = io.fetch.request.fire && !lineAllowed
    val perfDemandRefillRequest: Bool = fill.io.request.fire && demandFill
    val perfDemandRefillComplete: Bool = fill.io.response.fire && fill.io.response.bits.tag === 0.U
    val perfDemandRefillError: Bool = perfDemandRefillComplete && fill.io.response.bits.error
    val perfDemandRefillInstall: Bool = demandWrite
    val perfWaitingRefill: Bool = state === waitFill
    val perfWaitingPrefetch: Bool = state === waitPrefetch
    val perfFallbackActive: Bool = state === fallbackActive
    val perfRetryFallback: Bool = state === retryFallback
    def perfState: UInt = state

    when(state === retryFallback && fallbackFetch.request.fire) { state := fallbackActive }

    val useFallbackA = state === fallbackActive || state === retryFallback ||
        (acceptWindow && io.fetch.request.valid && !lineAllowed && !prefetchReply)
    val useFallbackD = io.tl.d.bits.source(2)
    val lockedA = RegInit(false.B)
    val lockedFallback = Reg(Bool())
    val chooseFallback = Mux(lockedA, lockedFallback, useFallbackA)
    io.tl.a.valid := Mux(chooseFallback, fallback.io.tl.a.valid, fill.io.tl.a.valid)
    io.tl.a.bits := Mux(chooseFallback, fallback.io.tl.a.bits, fill.io.tl.a.bits)
    when(chooseFallback) { io.tl.a.bits.source := fallback.io.tl.a.bits.source | 4.U }
    fallback.io.tl.a.ready := io.tl.a.ready && chooseFallback
    fill.io.tl.a.ready := io.tl.a.ready && !chooseFallback
    when(io.tl.a.valid && !io.tl.a.ready) {
        lockedA := true.B
        lockedFallback := chooseFallback
    }.elsewhen(io.tl.a.fire) { lockedA := false.B }
    fallback.io.tl.d.valid := io.tl.d.valid && useFallbackD
    fallback.io.tl.d.bits := io.tl.d.bits
    fallback.io.tl.d.bits.source := io.tl.d.bits.source & 3.U
    fill.io.tl.d.valid := io.tl.d.valid && !useFallbackD
    fill.io.tl.d.bits := io.tl.d.bits
    io.tl.d.ready := Mux(useFallbackD, fallback.io.tl.d.ready, fill.io.tl.d.ready)
    for (master <- Seq(fallback.io.tl, fill.io.tl)) {
        master.b.valid := false.B
        master.b.bits := 0.U.asTypeOf(master.b.bits)
        master.c.ready := false.B
        master.e.ready := false.B
    }
    io.tl.b.ready := false.B
    io.tl.c.valid := false.B
    io.tl.c.bits := 0.U.asTypeOf(io.tl.c.bits)
    io.tl.e.valid := false.B
    io.tl.e.bits := 0.U.asTypeOf(io.tl.e.bits)
    when(io.tl.b.valid) { assert(false.B, "instruction cache does not hold TL-C permissions") }
}
