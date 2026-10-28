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
    tagConfig: CacheTagConfig = CacheTagConfig.FullWidth,
    bankedData: Boolean = false,
    withRequestContext: Boolean = false,
    contextOwnedInstructionPrefetch: Boolean = false,
    sideEffectFreeFetchRanges: Seq[SideEffectFreeFetchRange] = Seq.empty
) extends Module {
    require(lines >= 4 && lines <= 512 && isPow2(lines))
    require(ramBase >= 0 && ramBase % 64 == 0 && ramBytes >= 64 && ramBytes % 64 == 0)
    require(ramBase + ramBytes <= (BigInt(1) << 64))
    require(params.addrWidth == 64 && params.dataWidth == 64 && params.sourceBits >= 3)
    require(Set(2, 4).contains(packetWords))
    require(!withRequestContext || !prefetchEnabled,
        "owner-context instruction cache requires context-owned prefetch before enabling prefetch")
    require(!contextOwnedInstructionPrefetch || (withRequestContext && packetWords == 2 && !prefetchEnabled),
        "context-owned prefetch requires its two-word certified owner port, never legacy prefetch")
    require(!contextOwnedInstructionPrefetch || sideEffectFreeFetchRanges.nonEmpty,
        "context-owned prefetch requires explicit side-effect-free physical RAM")
    require(!contextOwnedInstructionPrefetch || sideEffectFreeFetchRanges.forall(range =>
        range.base >= ramBase && range.endExclusive <= ramBase + ramBytes),
        "speculative fetch ranges must remain wholly inside the connected RAM aperture")
    private val sets = lines / 2
    private val prefetchSlots = if (contextOwnedInstructionPrefetch) 1 else 2
    private val indexBits = log2Ceil(sets)
    private val tagGeometry = tagConfig.geometry(ramBase, ramBytes, 6 + indexBits)
    private val tagBits = tagGeometry.tagBits
    val io = IO(new Bundle {
        val fetch = Flipped(new InstructionPort(packetWords, withRequestContext, contextOwnedInstructionPrefetch))
        val tl = new TLBundle(params)
        val pmpState = Input(new PmpState)
        val privilege = Input(UInt(2.W))
        val invalidate = Input(Bool())
        val idle = Output(Bool())
        val speculationKill = if (contextOwnedInstructionPrefetch) Some(Input(Bool())) else None
        val speculationMinimumSequence = if (contextOwnedInstructionPrefetch) Some(Input(UInt(64.W))) else None
        val speculationAgeUsable = if (contextOwnedInstructionPrefetch) Some(Input(Bool())) else None
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
    private val tags = if (!tagConfig.bankedStorage) Some(Reg(Vec(sets, Vec(2, UInt(tagBits.W))))) else None
    private val tagBanks = if (tagConfig.bankedStorage) Some(Seq.fill(2)(Mem(sets, UInt(tagBits.W)))) else None
    private val replace = RegInit(VecInit(Seq.fill(sets)(false.B)))
    private val data = if (!bankedData) Some(Seq.fill(2)(SyncReadMem(sets, UInt(512.W)))) else None
    // Combining way into the SRAM address doubles depth and narrows each port.
    // Capacity remains exactly lines * 64 bytes. The tag-selected way must now
    // meet the RAM address setup time; this is a real timing/packing tradeoff.
    private val dataBanks = if (bankedData) Some(Seq.fill(8)(SyncReadMem(lines, UInt(64.W)))) else None
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
    // One certificate lives from candidate reservation through engine terminal acceptance.
    // It is never overwritten while the sole speculative source is outstanding.
    private val contextPrefetchSequence = if (contextOwnedInstructionPrefetch) Some(Reg(UInt(64.W))) else None
    private val contextPrefetchPrivilege = if (contextOwnedInstructionPrefetch) Some(Reg(UInt(2.W))) else None
    private val contextPrefetchIdentity = if (contextOwnedInstructionPrefetch) Some(Reg(Bool())) else None
    private val contextSpecEligible = if (contextOwnedInstructionPrefetch) {
        !io.speculationKill.get && io.speculationAgeUsable.get && !io.invalidate &&
            contextPrefetchIdentity.get && contextPrefetchSequence.get >= io.speculationMinimumSequence.get
    } else true.B
    private val contextRequestEligible = if (contextOwnedInstructionPrefetch) {
        !io.speculationKill.get && io.speculationAgeUsable.get && !io.invalidate &&
            io.fetch.requestContext.get.identityTranslation.get &&
            io.fetch.requestContext.get.sourceSequence.get >= io.speculationMinimumSequence.get
    } else true.B

    private val requestPc = io.fetch.request.bits
    private val requestLine = Cat(requestPc(63, 6), 0.U(6.W))
    private val requestSet = requestPc(5 + indexBits, 6)
    private val requestTag = tagGeometry.tag(requestPc)
    private val demandTags = tagBanks.map(banks => VecInit(banks.map(_.read(requestSet))))
    private val inRam = requestLine >= ramBase.U &&
        (requestLine +& 63.U) < (ramBase + ramBytes).U(65.W)
    private val pmp = Module(new PmpChecker(16, alignedLineAccess = true, sharedAlignedBounds = true))
    pmp.io.state := io.pmpState
    pmp.io.address := requestLine
    pmp.io.size := 6.U
    pmp.io.privilege := io.fetch.requestContext.map(_.privilege).getOrElse(io.privilege)
    pmp.io.access := PmpAccess.execute
    if (withRequestContext) {
        val offer = Cat(io.fetch.request.bits, io.fetch.requestMask, io.fetch.requestContext.get.asUInt)
        val held = RegNext(io.fetch.request.valid && !io.fetch.request.ready, false.B)
        val previous = RegEnable(offer, io.fetch.request.valid && !io.fetch.request.ready)
        when(held && !reset.asBool) {
            assert(io.fetch.request.valid && offer === previous,
                "instruction cache held demand changed its address/mask/context")
        }
    }
    // This physical cache can serve sixteen-byte packets at eight-byte granularity.
    // Every offset 0..48 fits in one 64-byte line; only offset 56 needs precise fallback.
    // savedOffset already selects either hit SRAM data or the filled line at eight-byte granularity.
    private val packetFitsLine = if (packetWords == 4) requestPc(5, 3) =/= 7.U else true.B
    private val lineAllowed = inRam && requestPc(2, 0) === 0.U && packetFitsLine &&
        io.fetch.requestMask === ((1 << packetWords) - 1).U && !pmp.io.denied
    private val hits = VecInit((0 until 2).map { way =>
        tagGeometry.qualifies(requestPc) && valid(requestSet)(way) && (if (tagConfig.bankedStorage) demandTags.get(way) else tags.get(requestSet)(way)) === requestTag && !io.invalidate
    })
    private val hit = hits.asUInt.orR
    private val hitWay = hits(1)
    private val victim = Mux(!valid(requestSet)(0), false.B,
        Mux(!valid(requestSet)(1), true.B, replace(requestSet)))
    private val prefetchedPending = if (contextOwnedInstructionPrefetch) {
        prefetchOutstanding(0) && !prefetchStale(0) && prefetchLine(0) === requestLine &&
            !io.invalidate && contextSpecEligible && contextRequestEligible
    } else (0 until prefetchSlots).map(i =>
        prefetchOutstanding(i) && !prefetchStale(i) &&
            prefetchLine(i) === requestLine).reduce(_ || _) && !io.invalidate
    private val nextLine = requestLine + 64.U
    private val nextSet = nextLine(5 + indexBits, 6)
    private val nextTag = tagGeometry.tag(nextLine)
    private val speculativeTagSet = Mux(prefetchCandidate,
        (prefetchCandidateLine + 64.U)(5 + indexBits, 6), nextSet)
    private val speculativeTags = tagBanks.map(banks => VecInit(banks.map(_.read(speculativeTagSet))))
    private val nextCached = (0 until 2).map(way =>
        tagGeometry.qualifies(nextLine) && valid(nextSet)(way) && (if (tagConfig.bankedStorage) speculativeTags.get(way) else tags.get(nextSet)(way)) === nextTag).reduce(_ || _)
    private val nextPending = (0 until prefetchSlots).map(i =>
        prefetchOutstanding(i) && prefetchLine(i) === nextLine).reduce(_ || _)
    private val prefetchPmp = Module(new PmpChecker(16))
    prefetchPmp.io.state := io.pmpState
    prefetchPmp.io.address := nextLine
    prefetchPmp.io.size := 6.U
    prefetchPmp.io.privilege := (if (contextOwnedInstructionPrefetch)
        io.fetch.requestContext.get.privilege else io.privilege)
    prefetchPmp.io.access := PmpAccess.execute
    private val nextExecutable = requestLine(11, 6) =/= 63.U &&
        nextLine >= ramBase.U && (nextLine +& 63.U) < (ramBase + ramBytes).U(65.W) &&
        !prefetchPmp.io.denied && !nextCached
    private val contextNextInRam = if (contextOwnedInstructionPrefetch) {
        val nextWide = Cat(0.U(1.W), requestLine) + 64.U(65.W)
        val lastWide = nextWide + 63.U(65.W)
        !nextWide(64) && !lastWide(64) && sideEffectFreeFetchRanges.map(range =>
            nextWide >= range.base.U(65.W) && lastWide < range.endExclusive.U(65.W)).reduce(_ || _)
    } else false.B
    private val followingLine = prefetchCandidateLine + 64.U
    private val followingSet = followingLine(5 + indexBits, 6)
    private val followingTag = tagGeometry.tag(followingLine)
    private val followingCached = (0 until 2).map(way =>
        tagGeometry.qualifies(followingLine) && valid(followingSet)(way) && (if (tagConfig.bankedStorage) speculativeTags.get(way) else tags.get(followingSet)(way)) === followingTag).reduce(_ || _)
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
    private val responsePrefetchSlot = if (contextOwnedInstructionPrefetch) 0.U(1.W)
        else (fill.io.response.bits.tag - 1.U)(0)
    private val responsePrefetchLine = prefetchLine(responsePrefetchSlot)
    private val prefetchSet = responsePrefetchLine(5 + indexBits, 6)
    private val prefetchTag = tagGeometry.tag(responsePrefetchLine)
    private val prefetchVictim = Mux(!valid(prefetchSet)(0), false.B,
        Mux(!valid(prefetchSet)(1), true.B, replace(prefetchSet)))
    private val candidatePmp = Module(new PmpChecker(16))
    candidatePmp.io.state := io.pmpState
    candidatePmp.io.address := prefetchCandidateLine
    candidatePmp.io.size := 6.U
    candidatePmp.io.privilege := contextPrefetchPrivilege.getOrElse(io.privilege)
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

    val hitPacket = if (bankedData) {
        // Enable still requires the complete range/PMP/invalidate-qualified hit.
        // Its unused address outside that window need not carry those cones.
        val readWay = valid(requestSet)(1) &&
            (if (tagConfig.bankedStorage) demandTags.get(1) else tags.get(requestSet)(1)) === requestTag
        when(io.fetch.request.fire && lineAllowed && hit) {
            assert(readWay === hitWay, "instruction SRAM enabled-read way disagrees with qualified hit")
        }
        val readIndex = Cat(readWay, requestSet)
        val requestedWord = requestPc(5, 3)
        val words = VecInit((0 until 8).map { bank =>
            val selected = requestedWord === bank.U ||
                (if (packetWords == 4) requestedWord === ((bank + 7) % 8).U else false.B)
            dataBanks.get(bank).read(readIndex, io.fetch.request.fire && lineAllowed && hit && selected)
        })
        if (packetWords == 4) Cat(words((savedOffset + 1.U)(2, 0)), words(savedOffset))
        else words(savedOffset)
    } else {
        val readWords = VecInit((0 until 2).map { way =>
            data.get(way).read(requestSet, io.fetch.request.fire && lineAllowed && hits(way))
        })
        val hitData = Mux(savedWay, readWords(1), readWords(0))
        (hitData >> (savedOffset << 6))(packetWords * 32 - 1, 0)
    }
    io.fetch.response.valid := state === hitReply || state === lineReply ||
        (state === fallbackActive && fallbackFetch.response.valid)
    io.fetch.response.bits := Mux(state === hitReply, hitPacket,
        Mux(state === lineReply, replyData, fallbackFetch.response.bits))
    io.fetch.responseError := Mux(state === fallbackActive, fallbackFetch.responseError, 0.U)
    io.fetch.responsePageFault := Mux(state === fallbackActive, fallbackFetch.responsePageFault, 0.U)

    // A SyncReadMem result is defined only for the cycle following its read.
    // Retain the first stalled hit in the existing line-reply payload register;
    // later cycles must not depend on a disabled SRAM port or a new offer's set.
    when(state === hitReply && !io.fetch.response.ready) {
        replyData := hitPacket
        state := lineReply
    }

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
    if (contextOwnedInstructionPrefetch) {
        // Cancellation changes optional installation/admission only. An engine-accepted
        // source, including an A not yet offered, must still drain all eight D beats.
        when(!contextSpecEligible) {
            prefetchCandidate := false.B
            when(prefetchOutstanding(0)) { prefetchStale(0) := true.B }
        }
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
            if (contextOwnedInstructionPrefetch) {
                when(contextRequestEligible && nextExecutable && contextNextInRam &&
                    !nextPending && !prefetchCandidate && !prefetchOutstanding.asUInt.orR &&
                    (!hit || !prefetchStale(0) || nextLine =/= prefetchLine(0))) {
                    prefetchCandidate := true.B
                    prefetchCandidateLine := nextLine
                    contextPrefetchSequence.get := io.fetch.requestContext.get.sourceSequence.get
                    contextPrefetchPrivilege.get := io.fetch.requestContext.get.privilege
                    contextPrefetchIdentity.get := io.fetch.requestContext.get.identityTranslation.get
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
    val prefetchSlot = if (contextOwnedInstructionPrefetch) 0.U(1.W) else PriorityEncoder(freePrefetch)
    when(prefetchCandidate && candidatePmp.io.denied) { prefetchCandidate := false.B }
    if (contextOwnedInstructionPrefetch) {
        fill.io.request.valid := demandFill || (prefetchCandidate && !io.invalidate &&
            freePrefetch.asUInt.orR && !candidatePmp.io.denied && contextSpecEligible &&
            !(acceptWindow && io.fetch.request.valid && requestLine === prefetchCandidateLine))
    } else {
        fill.io.request.valid := demandFill || (prefetchCandidate && !io.invalidate &&
            freePrefetch.asUInt.orR && !candidatePmp.io.denied &&
            !(acceptWindow && io.fetch.request.valid && requestLine === prefetchCandidateLine))
    }
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
    val prefetchWrite = if (contextOwnedInstructionPrefetch) {
        fill.io.response.fire && fill.io.response.bits.tag =/= 0.U &&
            !prefetchStale(responsePrefetchSlot) && !io.invalidate && !fill.io.response.bits.error &&
            contextSpecEligible
    } else fill.io.response.fire && fill.io.response.bits.tag =/= 0.U &&
        !prefetchStale(responsePrefetchSlot) && !io.invalidate && !fill.io.response.bits.error
    val demandWrite = fill.io.response.fire && fill.io.response.bits.tag === 0.U &&
        !fill.io.response.bits.error && !staleFill && !io.invalidate
    for (way <- 0 until 2) {
        when((prefetchWrite && prefetchVictim === (way == 1).B) ||
            (demandWrite && savedWay === (way == 1).B)) {
            data.foreach(_(way).write(Mux(prefetchWrite, prefetchSet, savedSet), fill.io.response.bits.data))
            tagBanks.foreach(_(way).write(Mux(prefetchWrite, prefetchSet, savedSet),
                Mux(prefetchWrite, prefetchTag, savedTag)))
        }
    }
    if (bankedData) {
        val writeIndex = Cat(Mux(prefetchWrite, prefetchVictim, savedWay), Mux(prefetchWrite, prefetchSet, savedSet))
        when(prefetchWrite || demandWrite) {
            for (bank <- 0 until 8) {
                dataBanks.get(bank).write(writeIndex, fill.io.response.bits.data(64 * bank + 63, 64 * bank))
            }
            // Existing admission intentionally excludes a newly read hit on
            // every refill write cycle. No same-address RAM bypass is assumed.
            assert(!(io.fetch.request.fire && lineAllowed && hit),
                "packed instruction SRAM refill collided with a hit read")
        }
    }
    when(fill.io.response.fire) {
        when(fill.io.response.bits.tag =/= 0.U) {
            prefetchOutstanding(responsePrefetchSlot) := false.B
            when(if (contextOwnedInstructionPrefetch) prefetchWrite else
                !prefetchStale(responsePrefetchSlot) && !io.invalidate && !fill.io.response.bits.error) {
                if (tagConfig.compact) assert(tagGeometry.contains(responsePrefetchLine), "prefetch tag outside aperture")
                tags.foreach(_(prefetchSet)(prefetchVictim.asUInt) := prefetchTag)
                valid(prefetchSet)(prefetchVictim.asUInt) := true.B
                replace(prefetchSet) := !prefetchVictim
            }
            // A joined demand is a separate, irrevocable ordered response owner.
            // Kill/cutoff/age rollover may suppress install, NEVER this completion
            // or the exact original-PC/mask fallback after a late line error.
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
                tags.foreach(_(savedSet)(savedWay.asUInt) := savedTag)
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
    // Traffic must be reported separately: these are new optional size-six Gets,
    // not demand-route allocations. All observations are inert when disabled.
    val perfContextPrefetchRequest: Bool = if (contextOwnedInstructionPrefetch) {
        contextOwnedInstructionPrefetch.B && fill.io.request.fire && !demandFill
    } else false.B
    val perfContextPrefetchComplete: Bool = if (contextOwnedInstructionPrefetch) {
        contextOwnedInstructionPrefetch.B &&
        fill.io.response.fire && fill.io.response.bits.tag =/= 0.U
    } else false.B
    val perfContextPrefetchError: Bool = if (contextOwnedInstructionPrefetch) {
        perfContextPrefetchComplete && fill.io.response.bits.error
    } else false.B
    val perfContextPrefetchInstall: Bool = if (contextOwnedInstructionPrefetch) {
        contextOwnedInstructionPrefetch.B && prefetchWrite
    } else false.B
    val perfContextPrefetchStaleDrop: Bool = if (contextOwnedInstructionPrefetch) {
        perfContextPrefetchComplete &&
        (prefetchStale(responsePrefetchSlot) || !contextSpecEligible)
    } else false.B
    val perfContextPrefetchJoin: Bool = if (contextOwnedInstructionPrefetch) {
        contextOwnedInstructionPrefetch.B &&
        io.fetch.request.fire && lineAllowed && !hit && prefetchedPending
    } else false.B
    if (contextOwnedInstructionPrefetch) {
        assert(!(prefetchCandidate && prefetchOutstanding(0)),
            "context prefetch candidate and engine owner exceeded the single credit")
        when(fill.io.request.fire && !demandFill) {
            assert(prefetchCandidate && contextSpecEligible && !candidatePmp.io.denied,
                "context prefetch issued without its original certificate and full-line PMP")
            val last = Cat(0.U(1.W), prefetchCandidateLine) + 63.U(65.W)
            assert(!last(64) && sideEffectFreeFetchRanges.map(range =>
                prefetchCandidateLine >= range.base.U(64.W) &&
                    last < range.endExclusive.U(65.W)).reduce(_ || _),
                "context prefetch escaped explicit side-effect-free RAM")
        }
        when(fill.io.response.valid && fill.io.response.bits.tag =/= 0.U) {
            assert(fill.io.response.bits.tag === 1.U && prefetchOutstanding(0),
                "context prefetch completion has no sole engine owner")
        }
        when(prefetchWrite) {
            assert(contextSpecEligible && !prefetchStale(0), "stale context prefetch installed")
        }
        when(state === waitPrefetch) {
            assert(prefetchOutstanding(0) && savedLine === prefetchLine(0),
                "joined demand lost its original speculative transport owner")
        }
    }
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
    if (!prefetchEnabled && !contextOwnedInstructionPrefetch && packetWords == 2) {
        // Without speculative fills, a demand owner cannot offer fallback A
        // until its line transaction has completed (including an error retry).
        // The fill engine's registered send queue therefore selects address
        // data before live PMP/mask decides admission. Keep arbitration, valid,
        // ready, source namespace and the existing held-route lock unchanged.
        val ownedAddress = Mux(fill.io.tl.a.valid, fill.io.tl.a.bits.address, fallback.io.tl.a.bits.address)
        io.tl.a.bits.address := ownedAddress
        assert(!(fill.io.tl.a.valid && fallback.io.tl.a.valid),
            "non-prefetch instruction owners cannot offer fill and fallback together")
        when(io.tl.a.valid) {
            assert(ownedAddress === Mux(chooseFallback, fallback.io.tl.a.bits.address, fill.io.tl.a.bits.address),
                "early instruction address selection must preserve every valid A offer")
        }
    }
    when(chooseFallback) { io.tl.a.bits.source := fallback.io.tl.a.bits.source | 4.U }
    fallback.io.tl.a.ready := io.tl.a.ready && chooseFallback
    fill.io.tl.a.ready := io.tl.a.ready && !chooseFallback
    when(io.tl.a.valid && !io.tl.a.ready) {
        lockedA := true.B
        lockedFallback := chooseFallback
    }.elsewhen(io.tl.a.fire) { lockedA := false.B }
    if (contextOwnedInstructionPrefetch) {
        // Unlike the no-spec address fastpath, both producers may now be valid.
        // Every payload field must follow the same locked producer selection.
        val selected = WireDefault(Mux(chooseFallback, fallback.io.tl.a.bits, fill.io.tl.a.bits))
        when(chooseFallback) { selected.source := fallback.io.tl.a.bits.source | 4.U }
        when(io.tl.a.valid) {
            assert(io.tl.a.bits.asUInt === selected.asUInt,
                "context prefetch/fallback arbiter mixed address and owner metadata")
        }
        val wasHeld = RegNext(io.tl.a.valid && !io.tl.a.ready, false.B)
        val heldPayload = RegEnable(io.tl.a.bits.asUInt, io.tl.a.valid && !io.tl.a.ready)
        when(wasHeld && !reset.asBool) {
            assert(io.tl.a.valid && io.tl.a.bits.asUInt === heldPayload,
                "kill or demand arrival changed an irrevocable instruction A offer")
        }
    }
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
