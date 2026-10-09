package soc.core.ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.loadMemoryFromFileInline

class InstructionPort(val packetWords: Int = 2) extends Bundle {
    require(Set(2, 4).contains(packetWords))
    val request  = Decoupled(UInt(64.W))
    // Bit i authorizes the 32-bit word at request.bits + 4*i. Zero yields a fault-only packet.
    val requestMask = Output(UInt(packetWords.W))
    val response = Flipped(Decoupled(UInt((packetWords * 32).W)))
    // One error bit per 32-bit word, aligned with the response data while valid is asserted.
    val responseError = Input(UInt(packetWords.W))
    val responsePageFault = Input(UInt(packetWords.W))
}

/** Two synchronous 32-bit banks. Timing and initialization contract: docs/fpga-bringup.md. */
class InstructionRom(words: Int, base: BigInt, files: Seq[String] = Seq.empty, programmable: Boolean = false,
    vivadoNative: Boolean = false)
    extends Module {
    require(words >= 4 && isPow2(words))
    require(base >= 0 && base % 8 == 0 && base + BigInt(words) * 4 <= (BigInt(1) << 64))
    require(files.isEmpty || files.size == 2)
    require(!vivadoNative || (words == 32768 && files.isEmpty && !programmable),
        "blk_mem_gen_0 is a fixed 128 KiB ROM initialized by the Vivado COE file")
    val io = IO(new Bundle {
        val fetch = Flipped(new InstructionPort)
        val write =
            if (programmable) Some(Input(Valid(new Bundle {
                val index = UInt(log2Ceil(words).W)
                val data  = UInt(32.W)
            })))
            else None
    })
    val valid    = RegInit(false.B)
    val held     = RegInit(false.B)
    val heldData = Reg(UInt(64.W))
    val heldError = Reg(UInt(2.W))
    val odd      = Reg(Bool())
    val inRange  = Reg(Vec(2, Bool()))
    val writing  = io.write.map(_.valid).getOrElse(false.B)
    io.fetch.request.ready := (!valid || io.fetch.response.ready) && !writing
    val address   = io.fetch.request.bits
    val index     = ((address - base.U) >> 2)(log2Ceil(words) - 1, 0)
    val evenIndex = (index >> 1) + index(0)
    val evenRead = Mux(index(0), io.fetch.requestMask(1), io.fetch.requestMask(0))
    val oddRead  = Mux(index(0), io.fetch.requestMask(0), io.fetch.requestMask(1))
    val (word0, word1) = if (vivadoNative) {
        val memory = Module(new VivadoBootRom)
        memory.io.clka := clock
        memory.io.clkb := clock
        memory.io.ena := io.fetch.request.fire && io.fetch.requestMask(0)
        memory.io.enb := io.fetch.request.fire && io.fetch.requestMask(1)
        memory.io.addra := index
        memory.io.addrb := index + 1.U
        (memory.io.douta, memory.io.doutb)
    } else {
        val banks = Seq.fill(2)(SyncReadMem(words / 2, UInt(32.W)))
        for ((memory, i) <- banks.zipWithIndex) {
            if (files.nonEmpty) loadMemoryFromFileInline(memory, files(i))
            io.write.foreach { w =>
                when(w.valid && w.bits.index(0) === i.U) {
                    memory.write(w.bits.index(log2Ceil(words) - 1, 1), w.bits.data)
                }
            }
        }
        val even = banks(0).read(evenIndex(log2Ceil(words) - 2, 0), io.fetch.request.fire && evenRead)
        val oddWord = banks(1).read(index(log2Ceil(words) - 1, 1), io.fetch.request.fire && oddRead)
        (Mux(odd, oddWord, even), Mux(odd, even, oddWord))
    }
    val first     = Mux(inRange(0), word0, 0.U)
    val second    = Mux(inRange(1), word1, 0.U)
    val result    = Cat(second, first)
    io.fetch.response.valid := valid
    io.fetch.response.bits  := Mux(held, heldData, result)
    val errors = Cat(!inRange(1), !inRange(0))
    io.fetch.responseError := Mux(held, heldError, errors)
    io.fetch.responsePageFault := 0.U
    when(valid && !io.fetch.response.ready && !held) {
        held := true.B
        heldData := result
        heldError := errors
    }
    when(io.fetch.response.fire) { valid := false.B }
    when(io.fetch.request.fire) {
        assert(address(1, 0) === 0.U)
        valid := true.B
        held  := false.B
        odd   := index(0)
        for (lane <- 0 until 2) {
            val pc = address +& (4 * lane).U
            inRange(lane) := io.fetch.requestMask(lane) &&
                pc >= base.U(65.W) && pc < (base + BigInt(words) * 4).U(65.W)
        }
    }
    io.write.foreach(w => when(w.valid) { assert(!valid, "program ROM only while fetch is idle") })
}

/** Packet-granular instruction cache with sequential lookahead. Compressed configurations use two ways and
  * cacheSets sets of 8-byte packets; the non-compressed FPGA baseline retains two packet slots. At most one
  * response remains outstanding after each edge. The response bypass reaches decode, but request addressing
  * never depends on same-cycle instruction acceptance.
  */
class SynchronousFetch(pmpEntries: Int = 0, compressed: Boolean = false, cacheSets: Int = 64,
    fetchWidth: Int = 2, stableFaultMetadata: Boolean = false, alignedFetchPmp: Boolean = false,
    rawFetchPresence: Boolean = false, parallelFetchTagLookup: Boolean = false,
    parallelAlignment: Boolean = false, registeredWindow: Boolean = false,
    independentPayloadCapture: Boolean = false, fetchPreviousPacket: Boolean = false) extends Module {
    require(cacheSets >= 2 && isPow2(cacheSets))
    require(Set(2, 4).contains(fetchWidth), "fetch supports two or four instruction lanes")
    require(!alignedFetchPmp || compressed, "aligned PMP requires packet-aligned compressed requests")
    require(!rawFetchPresence || (compressed && stableFaultMetadata),
        "raw presence requires compressed packets and stable fault metadata")
    require(!parallelFetchTagLookup || compressed, "parallel tag lookup requires compressed packets")
    require(!parallelAlignment || compressed, "parallel alignment requires compressed packets")
    require(!registeredWindow || compressed, "registered window requires compressed packets")
    require(!fetchPreviousPacket || registeredWindow, "previous fetch packet requires the registered window")
    require(!independentPayloadCapture || compressed, "independent payload capture requires compressed packets")
    private val fetchWords = if (compressed && fetchWidth == 4) 4 else 2
    val io = IO(new Bundle {
        val pc           = Input(UInt(64.W))
        val enable       = Input(Bool())
        val invalidate   = Input(Bool())
        val pause        = Input(Bool())
        val quiescent    = Output(Bool())
        val pmpState     = Input(new PmpState)
        val privilege    = Input(UInt(2.W))
        val virtualized  = Input(Bool())
        val memory       = new InstructionPort(fetchWords)
        val instruction0 = Output(Valid(UInt(32.W)))
        val instruction1 = Output(Valid(UInt(32.W)))
        val instructions = Output(Vec(fetchWidth, Valid(UInt(32.W))))
        val instructionFaults = Output(Vec(fetchWidth, Bool()))
        val instructionPageFaults = Output(Vec(fetchWidth, Bool()))
        val instructionFaultAddresses = Output(Vec(fetchWidth, UInt(64.W)))
    })
    io.instructions(0) := io.instruction0
    io.instructions(1) := io.instruction1
    if (compressed) {
        val indexHigh = log2Ceil(cacheSets) + 2
        val valid = RegInit(VecInit(Seq.fill(cacheSets)(VecInit(Seq.fill(2)(false.B)))))
        val bases = Reg(Vec(cacheSets, Vec(2, UInt(64.W))))
        // Fill-time keys for queries at currentBase + 8/16/24. These retain all
        // 64 address bits; only the short set index advances on the read path.
        val maxPacketOffset = if (registeredWindow && fetchWidth == 4) 4 else 3
        val shiftedBases = (1 to maxPacketOffset).map(_ => Reg(Vec(cacheSets, Vec(2, UInt(64.W)))))
        val contexts = Reg(Vec(cacheSets, Vec(2, UInt(3.W))))
        val words = Reg(Vec(cacheSets, Vec(2, UInt(64.W))))
        val errors = Reg(Vec(cacheSets, Vec(2, UInt(2.W))))
        val pageFaults = Reg(Vec(cacheSets, Vec(2, UInt(2.W))))
        val replace = RegInit(VecInit(Seq.fill(cacheSets)(false.B)))
        val context = Cat(io.virtualized, io.privilege)
        val pending = RegInit(false.B)
        val pendingBase = Reg(UInt(64.W))
        val pendingBasePlusEight = Reg(UInt(64.W))
        val pendingBaseMinus = (1 to maxPacketOffset).map(_ => Reg(UInt(64.W)))
        val pendingContext = Reg(UInt(3.W))
        val pendingStale = RegInit(false.B)
        val locked = RegInit(false.B)
        val lockedBase = Reg(UInt(64.W))
        val lockedContext = Reg(UInt(3.W))
        val lockedMask = Reg(UInt(fetchWords.W))
        val lockedStale = RegInit(false.B)
        val returningPayload = io.memory.response.valid && pending && !pendingStale && pendingContext === context
        val returning = returningPayload && !io.invalidate

        def packetIndex(base: UInt, packetOffset: Int): UInt =
            if (packetOffset == 0) base(indexHigh, 3)
            else (base(indexHigh, 3) + packetOffset.U)(log2Ceil(cacheSets) - 1, 0)
        def cacheKeys(packetOffset: Int) =
            if (packetOffset == 0) bases else shiftedBases(packetOffset - 1)
        def cacheHits(base: UInt, packetOffset: Int = 0): (Bool, Bool) = if (parallelFetchTagLookup) {
            val lookup = Module(new ParallelFetchTagLookup(cacheSets, packetOffset))
            lookup.io.address := base
            lookup.io.context := context
            val present = Wire(Vec(cacheSets * 2, Bool()))
            for (set <- 0 until cacheSets; way <- 0 until 2) {
                val slot = set * 2 + way
                lookup.io.bases(slot) := cacheKeys(packetOffset)(set)(way)
                lookup.io.contexts(slot) := contexts(set)(way)
                present(slot) := valid(set)(way)
            }
            lookup.io.valid := present.asUInt
            (lookup.io.hit(0), lookup.io.hit(1))
        } else {
            val index = packetIndex(base, packetOffset)
            (valid(index)(0) && cacheKeys(packetOffset)(index)(0) === base && contexts(index)(0) === context,
                valid(index)(1) && cacheKeys(packetOffset)(index)(1) === base && contexts(index)(1) === context)
        }

        val pendingKeys = Seq(pendingBase) ++ pendingBaseMinus
        def pendingMatches(base: UInt, packetOffset: Int): (Bool, Bool) = {
            val low = pendingKeys(packetOffset) === base
            val high = if (fetchWords == 4) {
                val highKey = if (packetOffset == 0) pendingBasePlusEight else pendingKeys(packetOffset - 1)
                highKey === base
            } else false.B
            (low, high)
        }
        def packetAt(address: UInt, packetOffset: Int): (Bool, UInt, UInt, UInt) = {
            val base = Cat(address(63, 3), 0.U(3.W))
            val index = packetIndex(base, packetOffset)
            val (hit0, hit1) = cacheHits(base, packetOffset)
            val (lowHalf, highHalf) = pendingMatches(base, packetOffset)
            val bypass = (if (rawFetchPresence) returningPayload else returning) &&
                (lowHalf || highHalf)
            val returnedData = if (fetchWords == 4)
                Mux(highHalf, io.memory.response.bits(127, 64), io.memory.response.bits(63, 0))
                else io.memory.response.bits
            val returnedError = if (fetchWords == 4)
                Mux(highHalf, io.memory.responseError(3, 2), io.memory.responseError(1, 0))
                else io.memory.responseError
            val returnedPage = if (fetchWords == 4)
                Mux(highHalf, io.memory.responsePageFault(3, 2), io.memory.responsePageFault(1, 0))
                else io.memory.responsePageFault
            val data = Mux(hit0, words(index)(0), Mux(hit1, words(index)(1), returnedData))
            val error = Mux(hit0, errors(index)(0), Mux(hit1, errors(index)(1), returnedError))
            val page = Mux(hit0, pageFaults(index)(0), Mux(hit1, pageFaults(index)(1), returnedPage))
            // Invalidate suppresses instruction validity, but must not enter the cache data mux.
            // Otherwise a backend redirect can feed through fetch data and decode in one cycle.
            // Request payload uses raw presence; invalidation still suppresses
            // every instruction-valid lane and every new request handshake.
            ((if (rawFetchPresence) true.B else !io.invalidate) && (hit0 || hit1 || bypass), data, error, page)
        }
        // All four instruction lanes lie within these three adjacent 8-byte packets.
        // Read each cache packet once instead of building two dynamic cache read ports per lane.
        val currentBase = Cat(io.pc(63, 3), 0.U(3.W))
        val nextBase = currentBase + 8.U
        val nextTwoBase = currentBase + 16.U
        val queryCapacity = if (registeredWindow && fetchWidth == 4) 5 else 3
        val queriedPackets = (0 until queryCapacity).map(offset => packetAt(currentBase, offset))
        val suppliedPackets = if (registeredWindow) {
            val window = Module(new RegisteredFetchWindow(queryCapacity, previousPacket = fetchPreviousPacket))
            window.io.queryBase := currentBase
            window.io.queryContext := context
            window.io.readBase := currentBase
            window.io.readContext := context
            window.io.invalidate := io.invalidate
            for (row <- 0 until queryCapacity) {
                val (present, data, error, page) = queriedPackets(row)
                window.io.query(row).valid := present
                window.io.query(row).bits.data := data
                window.io.query(row).bits.accessFaults := error
                window.io.query(row).bits.pageFaults := page
            }
            (0 until 3).map { row =>
                val packet = window.io.packets(row)
                (packet.valid, packet.bits.data, packet.bits.accessFaults, packet.bits.pageFaults)
            }
        } else queriedPackets
        val (currentPresent, currentData, currentErrors, currentPages) = suppliedPackets(0)
        val (nextPresent, nextData, nextErrors, nextPages) = suppliedPackets(1)
        val (nextTwoPresent, nextTwoData, nextTwoErrors, nextTwoPages) = suppliedPackets(2)

        // Decode stays within three adjacent packets. Select them with a 5-bit
        // byte offset, not a data-dependent XLEN addition and address comparison.
        // Full addresses are only needed for precise instruction-fault tval.
        def packetFor(offset: UInt): (Bool, UInt, UInt, UInt) = {
            val current = offset(4, 3) === 0.U
            val next = offset(4, 3) === 1.U
            val nextTwo = offset(4, 3) === 2.U
            val selected = Seq(current, next, nextTwo)
            (
                current && currentPresent || next && nextPresent || nextTwo && nextTwoPresent,
                Mux1H(selected.zip(Seq(currentData, nextData, nextTwoData))),
                Mux1H(selected.zip(Seq(currentErrors, nextErrors, nextTwoErrors))),
                Mux1H(selected.zip(Seq(currentPages, nextPages, nextTwoPages)))
            )
        }
        def instructionAt(offset: UInt): (Bool, UInt, Bool, Bool, UInt) = {
            val (firstValid, firstData, firstErrors, firstPages) = packetFor(offset)
            val secondOffset = offset + 2.U(5.W)
            val (secondValid, secondData, secondErrors, secondPages) = packetFor(secondOffset)
            val firstHalf = MuxLookup(offset(2, 1), firstData(15, 0))(Seq(
                1.U -> firstData(31, 16), 2.U -> firstData(47, 32), 3.U -> firstData(63, 48)))
            val secondHalf = MuxLookup(secondOffset(2, 1), secondData(15, 0))(Seq(
                1.U -> secondData(31, 16), 2.U -> secondData(47, 32), 3.U -> secondData(63, 48)))
            val short = firstHalf(1, 0) =/= 3.U
            val error = firstErrors(offset(2)) || (!short && secondErrors(secondOffset(2)))
            val page = firstPages(offset(2)) || (!short && secondPages(secondOffset(2)))
            val firstFault = firstErrors(offset(2)) || firstPages(offset(2))
            (firstValid && (short || secondValid), Mux(short, Cat(0.U(16.W), firstHalf),
                Cat(secondHalf, firstHalf)), error, page,
                currentBase + Mux(firstFault, offset, secondOffset))
        }

        val alignment = if (parallelAlignment) {
            val helper = Module(new ParallelFetchAlignment(fetchWidth))
            helper.io.packets := VecInit(Seq(currentData, nextData, nextTwoData))
            helper.io.present := VecInit(Seq(currentPresent, nextPresent, nextTwoPresent)).asUInt
            helper.io.errors := VecInit(Seq(currentErrors, nextErrors, nextTwoErrors))
            helper.io.pages := VecInit(Seq(currentPages, nextPages, nextTwoPages))
            helper.io.pcOffset := io.pc(2, 0)
            Some(helper)
        } else None
        def alignedAt(lane: Int, offset: UInt): (Bool, UInt, Bool, Bool, UInt) = alignment.map { helper =>
            (helper.io.instructions(lane).valid, helper.io.instructions(lane).bits,
                helper.io.errorsOut(lane), helper.io.pagesOut(lane), currentBase + helper.io.faultOffsets(lane))
        }.getOrElse(instructionAt(offset))
        val firstOffset = Cat(0.U(2.W), io.pc(2, 0))
        val (firstValid, firstInstruction, firstError, firstPage, firstFaultAddress) = alignedAt(0, firstOffset)
        val secondOffset = firstOffset + Mux(firstInstruction(1, 0) === 3.U, 4.U(5.W), 2.U(5.W))
        val (secondValid, secondInstruction, secondError, secondPage, secondFaultAddress) = alignedAt(1, secondOffset)
        io.instruction0.valid := io.enable && firstValid && (if (rawFetchPresence) !io.invalidate else true.B)
        io.instruction0.bits := firstInstruction
        io.instruction1.valid := io.enable && firstValid && secondValid &&
            (if (rawFetchPresence) !io.invalidate else true.B)
        io.instruction1.bits := secondInstruction
        // Payload/exception metadata are meaningful only when the lane is valid.
        // Suppress validity on invalidation, never feed kill back through decode.
        io.instructionFaults(0) := (if (stableFaultMetadata) firstError else io.instruction0.valid && firstError)
        io.instructionFaults(1) := (if (stableFaultMetadata) secondError else io.instruction1.valid && secondError)
        io.instructionPageFaults(0) := (if (stableFaultMetadata) firstPage else io.instruction0.valid && firstPage)
        io.instructionPageFaults(1) := (if (stableFaultMetadata) secondPage else io.instruction1.valid && secondPage)
        io.instructionFaultAddresses(0) := firstFaultAddress
        io.instructionFaultAddresses(1) := secondFaultAddress
        if (fetchWidth == 4) {
            val laneOffset = Wire(Vec(4, UInt(5.W)))
            laneOffset(0) := firstOffset
            laneOffset(1) := secondOffset
            for (lane <- 2 until 4) {
                laneOffset(lane) := laneOffset(lane - 1) +
                    Mux(io.instructions(lane - 1).bits(1, 0) === 3.U, 4.U, 2.U)
                val (present, instruction, error, page, faultAddress) = alignedAt(lane, laneOffset(lane))
                io.instructions(lane).valid := io.instructions(lane - 1).valid && present
                io.instructions(lane).bits := instruction
                io.instructionFaults(lane) := (if (stableFaultMetadata) error else io.instructions(lane).valid && error)
                io.instructionPageFaults(lane) := (if (stableFaultMetadata) page else io.instructions(lane).valid && page)
                io.instructionFaultAddresses(lane) := faultAddress
            }
        }

        // Four lanes can consume two complete packets in one cycle, and a 32-bit
        // instruction straddling the second boundary can need a third. Keep one
        // further packet prefetched so a full-width cycle does not exhaust the
        // available instruction window before the next response returns.
        // Scheduling uses the LIVE cache/return presence, never the delayed
        // decode window. A snapshot miss must not duplicate an owned request.
        val currentCached = queriedPackets(0)._1
        val nextCached = queriedPackets(1)._1
        val nextTwoCached = queriedPackets(2)._1
        val wanted = if (fetchWidth == 4) {
            Mux(!currentCached, currentBase,
                Mux(!nextCached, nextBase,
                    Mux(!nextTwoCached, nextTwoBase, nextTwoBase + 8.U)))
        } else Mux(currentCached, nextBase, currentBase)
        val wantedPacket = if (fetchWidth == 4)
            Mux(!currentCached, 0.U(2.W),
                Mux(!nextCached, 1.U(2.W), Mux(!nextTwoCached, 2.U(2.W), 3.U(2.W))))
        else Mux(currentCached, 1.U(2.W), 0.U(2.W))
        val fourthPresent = if (fetchWidth == 4) {
            val (hit0, hit1) = cacheHits(currentBase, 3)
            (if (rawFetchPresence) true.B else !io.invalidate) && (hit0 || hit1)
        } else false.B
        val cachedTarget = if (fetchWidth == 4)
            currentCached && nextCached && nextTwoCached && fourthPresent
        else currentCached && nextCached
        // Equality is modulo-XLEN: base+8*k == pendingBase (+8 for the
        // response high half) iff base equals its request-time shifted key.
        // Keep returning/context/stale authorization unchanged.
        val returningMatches = (0 to (if (fetchWidth == 4) 3 else 1)).map { offset =>
            val (low, high) = pendingMatches(currentBase, offset)
            offset.U -> (low || high)
        }
        val returningTarget = returning && MuxLookup(wantedPacket, false.B)(returningMatches)
        val reply = io.memory.response.valid && pending
        io.memory.request.valid := !reset.asBool && (locked ||
            (io.enable && !io.pause && !io.invalidate && (!pending || reply) &&
                !cachedTarget && !returningTarget))
        val fetchBase = if (fetchWords == 4) Cat(wanted(63, 4), 0.U(4.W)) else wanted
        io.memory.request.bits := Mux(locked, lockedBase, fetchBase)
        val allowed = Wire(Vec(fetchWords, Bool()))
        for (lane <- 0 until fetchWords) {
            val checker = Module(new PmpChecker(pmpEntries, alignedWordAccess = alignedFetchPmp))
            checker.io.state := io.pmpState
            // An unlocked request base is aligned to the whole 8/16-byte packet.
            // Locked requests use the previously captured mask, never this live
            // checker result. Thus no locked-base mux or XLEN lane/end addition
            // is needed on the new request's permission-payload path.
            checker.io.address := (if (alignedFetchPmp)
                Cat(fetchBase(63, log2Ceil(fetchWords * 4)), lane.U(log2Ceil(fetchWords).W), 0.U(2.W))
                else io.memory.request.bits + (4 * lane).U)
            checker.io.size := 2.U
            checker.io.privilege := io.privilege
            checker.io.access := PmpAccess.execute
            allowed(lane) := !checker.io.denied
        }
        io.memory.requestMask := Mux(locked, lockedMask,
            Mux(io.virtualized, ((1 << fetchWords) - 1).U, allowed.asUInt))
        io.memory.response.ready := true.B
        io.quiescent := !pending && !locked
        when(io.memory.request.valid && !io.memory.request.ready) {
            locked := true.B
            lockedBase := io.memory.request.bits
            lockedContext := context
            lockedMask := io.memory.requestMask
        }
        when(io.invalidate) {
            for (set <- 0 until cacheSets; way <- 0 until 2) valid(set)(way) := false.B
            when(pending) { pendingStale := true.B }
            when(locked) { lockedStale := true.B }
        }
        when(io.memory.response.fire) {
            assert(pending, "compressed fetch response must follow a request")
            pending := false.B
            pendingStale := false.B
            for (packet <- 0 until fetchWords / 2) {
                val packetBase = if (packet == 0) pendingBase else pendingBasePlusEight
                val index = packetBase(indexHigh, 3)
                val protect0 = io.enable && valid(index)(0) && bases(index)(0) === currentBase &&
                    contexts(index)(0) === context
                val protect1 = io.enable && valid(index)(1) && bases(index)(1) === currentBase &&
                    contexts(index)(1) === context
                val victim = Mux(protect0, true.B, Mux(protect1, false.B,
                    Mux(!valid(index)(0), false.B, Mux(!valid(index)(1), true.B, replace(index)))))
                def capturePayload(): Unit = {
                    bases(index)(victim.asUInt) := packetBase
                    for (offset <- 1 to maxPacketOffset) {
                        // A 16-byte response's second packet is +8 from its
                        // owner. Shifted owner keys already contain every key.
                        shiftedBases(offset - 1)(index)(victim.asUInt) := pendingKeys(offset - packet)
                    }
                    contexts(index)(victim.asUInt) := pendingContext
                    words(index)(victim.asUInt) := io.memory.response.bits(64 * packet + 63, 64 * packet)
                    errors(index)(victim.asUInt) := io.memory.responseError(2 * packet + 1, 2 * packet)
                    pageFaults(index)(victim.asUInt) := io.memory.responsePageFault(2 * packet + 1, 2 * packet)
                }
                when(!pendingStale && !io.invalidate) {
                    valid(index)(victim.asUInt) := true.B
                    if (!independentPayloadCapture) capturePayload()
                    replace(index) := !victim
                }
                if (independentPayloadCapture) {
                    // Invalidate clears validity on this edge. Capturing an
                    // otherwise live owner's dead payload is harmless and
                    // keeps late trap/redirect qualification out of data CE.
                    // A delayed stale owner must still never overwrite a live
                    // resident payload, even if invalidate is no longer high.
                    when(!pendingStale) { capturePayload() }
                }
            }
        }
        when(io.memory.request.fire) {
            assert(!pending || reply, "compressed fetch permits one outstanding packet")
            locked := false.B
            lockedStale := false.B
            pending := true.B
            pendingStale := io.invalidate || lockedStale
            pendingBase := io.memory.request.bits
            pendingBasePlusEight := (io.memory.request.bits + 8.U)(63, 0)
            for (offset <- 1 to maxPacketOffset) {
                pendingBaseMinus(offset - 1) := (io.memory.request.bits - (8 * offset).U)(63, 0)
            }
            pendingContext := Mux(locked, lockedContext, context)
        }
    } else {
    val valid        = Seq.fill(2)(RegInit(false.B))
    val pcs          = Seq.fill(2)(Reg(UInt(64.W)))
    val data         = Seq.fill(2)(Reg(UInt(64.W)))
    val errors       = Seq.fill(2)(Reg(UInt(2.W)))
    val pageFaults   = Seq.fill(2)(Reg(UInt(2.W)))
    val replace      = RegInit(false.B)
    val pending      = RegInit(false.B)
    val pendingPc    = Reg(UInt(64.W))
    val pendingStale = RegInit(false.B)
    val locked       = RegInit(false.B)
    val lockedPc     = Reg(UInt(64.W))
    val lockedMask   = Reg(UInt(2.W))
    val lockedStale  = RegInit(false.B)
    val hits         = (0 until 2).map(i => valid(i) && (stableFaultMetadata.B || !io.invalidate) &&
        (io.pc === pcs(i) || io.pc === pcs(i) + 4.U))
    val reply        = io.memory.response.valid && pending
    val returning    = reply && !pendingStale && !io.invalidate
    val responseHit  = returning && (io.pc === pendingPc || io.pc === pendingPc + 4.U)
    val hit          = !io.invalidate && (hits.reduce(_ || _) || responseHit)
    val selectedPc   = Mux(hits(0), pcs(0), Mux(hits(1), pcs(1), pendingPc))
    val selectedData = Mux(hits(0), data(0), Mux(hits(1), data(1), io.memory.response.bits))
    val selectedErrors = Mux(hits(0), errors(0), Mux(hits(1), errors(1), io.memory.responseError))
    val selectedPageFaults = Mux(hits(0), pageFaults(0), Mux(hits(1), pageFaults(1), io.memory.responsePageFault))
    val first        = io.pc === selectedPc
    io.instruction0.valid := io.enable && hit
    io.instruction0.bits  := Mux(first, selectedData(31, 0), selectedData(63, 32))
    io.instructionFaults(0) := (stableFaultMetadata.B || io.instruction0.valid) &&
        Mux(first, selectedErrors(0), selectedErrors(1))
    io.instructionPageFaults(0) := (stableFaultMetadata.B || io.instruction0.valid) &&
        Mux(first, selectedPageFaults(0), selectedPageFaults(1))
    // A partially consumed packet may join its successor, including a response arriving this cycle.
    // Match lane one independently: a redirected/stale response must never fill an unrelated lane.
    val nextPc          = io.pc + 4.U
    val nextHits        = (0 until 2).map(i => valid(i) && (stableFaultMetadata.B || !io.invalidate) &&
        (nextPc === pcs(i) || nextPc === pcs(i) + 4.U))
    val nextResponseHit = returning && (nextPc === pendingPc || nextPc === pendingPc + 4.U)
    val nextPacketPc    = Mux(nextHits(0), pcs(0), Mux(nextHits(1), pcs(1), pendingPc))
    val nextData        = Mux(nextHits(0), data(0), Mux(nextHits(1), data(1), io.memory.response.bits))
    val nextErrors = Mux(nextHits(0), errors(0), Mux(nextHits(1), errors(1), io.memory.responseError))
    val nextPageFaults = Mux(nextHits(0), pageFaults(0), Mux(nextHits(1), pageFaults(1),
        io.memory.responsePageFault))
    io.instruction1.valid := io.enable && hit && (nextHits.reduce(_ || _) || nextResponseHit)
    io.instruction1.bits  := Mux(nextPc === nextPacketPc, nextData(31, 0), nextData(63, 32))
    io.instructionFaults(1) := (stableFaultMetadata.B || io.instruction1.valid) &&
        Mux(nextPc === nextPacketPc, nextErrors(0), nextErrors(1))
    io.instructionPageFaults(1) := (stableFaultMetadata.B || io.instruction1.valid) &&
        Mux(nextPc === nextPacketPc, nextPageFaults(0), nextPageFaults(1))
    io.instructionFaultAddresses(0) := io.pc
    io.instructionFaultAddresses(1) := nextPc
    if (fetchWidth == 4) {
        for (lane <- 2 until 4) {
            val lanePc = io.pc + (4 * lane).U
            val laneHits = (0 until 2).map(i => valid(i) && (stableFaultMetadata.B || !io.invalidate) &&
                (lanePc === pcs(i) || lanePc === pcs(i) + 4.U))
            val laneResponseHit = returning && (lanePc === pendingPc || lanePc === pendingPc + 4.U)
            val lanePacketPc = Mux(laneHits(0), pcs(0), Mux(laneHits(1), pcs(1), pendingPc))
            val laneData = Mux(laneHits(0), data(0), Mux(laneHits(1), data(1), io.memory.response.bits))
            val laneErrors = Mux(laneHits(0), errors(0), Mux(laneHits(1), errors(1), io.memory.responseError))
            val lanePages = Mux(laneHits(0), pageFaults(0), Mux(laneHits(1), pageFaults(1),
                io.memory.responsePageFault))
            val low = lanePc === lanePacketPc
            io.instructions(lane).valid := io.instructions(lane - 1).valid &&
                (laneHits.reduce(_ || _) || laneResponseHit)
            io.instructions(lane).bits := Mux(low, laneData(31, 0), laneData(63, 32))
            io.instructionFaults(lane) := (stableFaultMetadata.B || io.instructions(lane).valid) &&
                Mux(low, laneErrors(0), laneErrors(1))
            io.instructionPageFaults(lane) := (stableFaultMetadata.B || io.instructions(lane).valid) &&
                Mux(low, lanePages(0), lanePages(1))
            io.instructionFaultAddresses(lane) := lanePc
        }
    }

    val wanted          = Mux(hit, selectedPc + 8.U, io.pc)
    val cachedTarget    = (0 until 2).map(i => valid(i) && !io.invalidate && pcs(i) === wanted).reduce(_ || _)
    val returningTarget = returning && pendingPc === wanted
    val available       = !pending || reply
    io.memory.request.valid := !reset.asBool && (locked ||
        (io.enable && !io.pause && !io.invalidate && available && !cachedTarget && !returningTarget))
    io.memory.request.bits := Mux(locked, lockedPc, wanted)
    val allowed = Wire(Vec(2, Bool()))
    for (lane <- 0 until 2) {
        val checker = Module(new PmpChecker(pmpEntries))
        checker.io.state     := io.pmpState
        checker.io.address   := io.memory.request.bits + (4 * lane).U
        checker.io.size      := 2.U
        checker.io.privilege := io.privilege
        checker.io.access    := PmpAccess.execute
        allowed(lane) := !checker.io.denied
    }
    io.memory.requestMask := Mux(locked, lockedMask, Mux(io.virtualized, 3.U, allowed.asUInt))
    // The backend asserts pause before using quiescent; avoid a redirect -> request -> issue loop.
    io.quiescent := !pending && !locked
    // A synchronous response must follow an earlier handshake; always drain it, including after a redirect.
    io.memory.response.ready := true.B
    when(io.memory.request.valid && !io.memory.request.ready) {
        locked   := true.B
        lockedPc := io.memory.request.bits
        lockedMask := io.memory.requestMask
    }
    when(io.invalidate) {
        valid.foreach(v => v := false.B)
        when(pending) { pendingStale := true.B }
        when(locked) { lockedStale := true.B }
    }
    when(io.memory.response.fire) {
        assert(pending, "instruction response must follow an earlier request handshake")
        pending := false.B
        pendingStale := false.B
        // Preserve a packet the core is currently using, even when its successor returns during a stall.
        val victim = Mux(hits(0), true.B, Mux(hits(1), false.B, replace))
        when(!pendingStale && !io.invalidate) {
            for (i <- 0 until 2) {
                when(victim === (i == 1).B) {
                    valid(i) := true.B
                    pcs(i)   := pendingPc
                    data(i)  := io.memory.response.bits
                    errors(i) := io.memory.responseError
                    pageFaults(i) := io.memory.responsePageFault
                }
            }
            replace := !victim
        }
    }
    // New ownership wins when the old response and next request overlap.
    when(io.memory.request.fire) {
        assert(!pending || reply, "more than one outstanding instruction request")
        locked    := false.B
        lockedStale := false.B
        pending   := true.B
        pendingStale := io.invalidate || lockedStale
        pendingPc := io.memory.request.bits
    }
    }
}
