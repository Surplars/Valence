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
class InstructionRom(words: Int, base: BigInt, files: Seq[String] = Seq.empty, programmable: Boolean = false)
    extends Module {
    require(words >= 4 && isPow2(words))
    require(base >= 0 && base % 8 == 0 && base + BigInt(words) * 4 <= (BigInt(1) << 64))
    require(files.isEmpty || files.size == 2)
    val io = IO(new Bundle {
        val fetch = Flipped(new InstructionPort)
        val write =
            if (programmable) Some(Input(Valid(new Bundle {
                val index = UInt(log2Ceil(words).W)
                val data  = UInt(32.W)
            })))
            else None
    })
    val banks = Seq.fill(2)(SyncReadMem(words / 2, UInt(32.W)))
    for ((memory, i) <- banks.zipWithIndex) {
        if (files.nonEmpty) loadMemoryFromFileInline(memory, files(i))
        io.write.foreach { w =>
            when(w.valid && w.bits.index(0) === i.U) {
                memory.write(w.bits.index(log2Ceil(words) - 1, 1), w.bits.data)
            }
        }
    }
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
    val even      = banks(0).read(evenIndex(log2Ceil(words) - 2, 0), io.fetch.request.fire && evenRead)
    val oddWord   = banks(1).read(index(log2Ceil(words) - 1, 1), io.fetch.request.fire && oddRead)
    val first     = Mux(inRange(0), Mux(odd, oddWord, even), 0.U)
    val second    = Mux(inRange(1), Mux(odd, even, oddWord), 0.U)
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
    fetchWidth: Int = 2) extends Module {
    require(cacheSets >= 2 && isPow2(cacheSets))
    require(Set(2, 4).contains(fetchWidth), "fetch supports two or four instruction lanes")
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
        val contexts = Reg(Vec(cacheSets, Vec(2, UInt(3.W))))
        val words = Reg(Vec(cacheSets, Vec(2, UInt(64.W))))
        val errors = Reg(Vec(cacheSets, Vec(2, UInt(2.W))))
        val pageFaults = Reg(Vec(cacheSets, Vec(2, UInt(2.W))))
        val replace = RegInit(VecInit(Seq.fill(cacheSets)(false.B)))
        val context = Cat(io.virtualized, io.privilege)
        val pending = RegInit(false.B)
        val pendingBase = Reg(UInt(64.W))
        val pendingContext = Reg(UInt(3.W))
        val pendingStale = RegInit(false.B)
        val locked = RegInit(false.B)
        val lockedBase = Reg(UInt(64.W))
        val lockedContext = Reg(UInt(3.W))
        val lockedMask = Reg(UInt(fetchWords.W))
        val lockedStale = RegInit(false.B)
        val returning = io.memory.response.valid && pending && !pendingStale && !io.invalidate &&
            pendingContext === context

        def packetAt(address: UInt): (Bool, UInt, UInt, UInt) = {
            val base = Cat(address(63, 3), 0.U(3.W))
            val index = base(indexHigh, 3)
            val hit0 = valid(index)(0) && !io.invalidate && bases(index)(0) === base &&
                contexts(index)(0) === context
            val hit1 = valid(index)(1) && !io.invalidate && bases(index)(1) === base &&
                contexts(index)(1) === context
            val highHalf = if (fetchWords == 4) pendingBase + 8.U === base else false.B
            val bypass = returning && (pendingBase === base || highHalf)
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
            (hit0 || hit1 || bypass, data, error, page)
        }
        def instructionAt(address: UInt): (Bool, UInt, Bool, Bool, UInt) = {
            val (firstValid, firstData, firstErrors, firstPages) = packetAt(address)
            val secondAddress = address + 2.U
            val (secondValid, secondData, secondErrors, secondPages) = packetAt(secondAddress)
            val firstHalf = MuxLookup(address(2, 1), firstData(15, 0))(Seq(
                1.U -> firstData(31, 16), 2.U -> firstData(47, 32), 3.U -> firstData(63, 48)))
            val secondHalf = MuxLookup(secondAddress(2, 1), secondData(15, 0))(Seq(
                1.U -> secondData(31, 16), 2.U -> secondData(47, 32), 3.U -> secondData(63, 48)))
            val short = firstHalf(1, 0) =/= 3.U
            val error = firstErrors(address(2)) || (!short && secondErrors(secondAddress(2)))
            val page = firstPages(address(2)) || (!short && secondPages(secondAddress(2)))
            val firstFault = firstErrors(address(2)) || firstPages(address(2))
            (firstValid && (short || secondValid), Mux(short, Cat(0.U(16.W), firstHalf),
                Cat(secondHalf, firstHalf)), error, page, Mux(firstFault, address, secondAddress))
        }

        val (firstValid, firstInstruction, firstError, firstPage, firstFaultAddress) = instructionAt(io.pc)
        val secondPc = io.pc + Mux(firstInstruction(1, 0) === 3.U, 4.U, 2.U)
        val (secondValid, secondInstruction, secondError, secondPage, secondFaultAddress) = instructionAt(secondPc)
        io.instruction0.valid := io.enable && firstValid
        io.instruction0.bits := firstInstruction
        io.instruction1.valid := io.enable && firstValid && secondValid
        io.instruction1.bits := secondInstruction
        io.instructionFaults(0) := io.instruction0.valid && firstError
        io.instructionFaults(1) := io.instruction1.valid && secondError
        io.instructionPageFaults(0) := io.instruction0.valid && firstPage
        io.instructionPageFaults(1) := io.instruction1.valid && secondPage
        io.instructionFaultAddresses(0) := firstFaultAddress
        io.instructionFaultAddresses(1) := secondFaultAddress
        if (fetchWidth == 4) {
            val lanePc = Wire(Vec(4, UInt(64.W)))
            lanePc(0) := io.pc
            lanePc(1) := secondPc
            for (lane <- 2 until 4) {
                lanePc(lane) := lanePc(lane - 1) +
                    Mux(io.instructions(lane - 1).bits(1, 0) === 3.U, 4.U, 2.U)
                val (present, instruction, error, page, faultAddress) = instructionAt(lanePc(lane))
                io.instructions(lane).valid := io.instructions(lane - 1).valid && present
                io.instructions(lane).bits := instruction
                io.instructionFaults(lane) := io.instructions(lane).valid && error
                io.instructionPageFaults(lane) := io.instructions(lane).valid && page
                io.instructionFaultAddresses(lane) := faultAddress
            }
        }

        val currentBase = Cat(io.pc(63, 3), 0.U(3.W))
        val nextBase = currentBase + 8.U
        val nextTwoBase = nextBase + 8.U
        val (currentPresent, _, _, _) = packetAt(currentBase)
        val (nextPresent, _, _, _) = packetAt(nextBase)
        val (nextTwoPresent, _, _, _) = packetAt(nextTwoBase)
        // Four lanes can consume two complete packets in one cycle, and a 32-bit
        // instruction straddling the second boundary can need a third. Keep one
        // further packet prefetched so a full-width cycle does not exhaust the
        // available instruction window before the next response returns.
        val wanted = if (fetchWidth == 4) {
            Mux(!currentPresent, currentBase,
                Mux(!nextPresent, nextBase,
                    Mux(!nextTwoPresent, nextTwoBase, nextTwoBase + 8.U)))
        } else Mux(currentPresent, nextBase, currentBase)
        val (cachedTarget, _, _, _) = packetAt(wanted)
        val returningTarget = returning && (pendingBase === wanted ||
            (if (fetchWords == 4) pendingBase + 8.U === wanted else false.B))
        val reply = io.memory.response.valid && pending
        io.memory.request.valid := !reset.asBool && (locked ||
            (io.enable && !io.pause && !io.invalidate && (!pending || reply) &&
                !cachedTarget && !returningTarget))
        val fetchBase = if (fetchWords == 4) Cat(wanted(63, 4), 0.U(4.W)) else wanted
        io.memory.request.bits := Mux(locked, lockedBase, fetchBase)
        val allowed = Wire(Vec(fetchWords, Bool()))
        for (lane <- 0 until fetchWords) {
            val checker = Module(new PmpChecker(pmpEntries))
            checker.io.state := io.pmpState
            checker.io.address := io.memory.request.bits + (4 * lane).U
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
                val packetBase = pendingBase + (packet * 8).U
                val index = packetBase(indexHigh, 3)
                val protect0 = io.enable && valid(index)(0) && bases(index)(0) === currentBase &&
                    contexts(index)(0) === context
                val protect1 = io.enable && valid(index)(1) && bases(index)(1) === currentBase &&
                    contexts(index)(1) === context
                val victim = Mux(protect0, true.B, Mux(protect1, false.B,
                    Mux(!valid(index)(0), false.B, Mux(!valid(index)(1), true.B, replace(index)))))
                when(!pendingStale && !io.invalidate) {
                    valid(index)(victim.asUInt) := true.B
                    bases(index)(victim.asUInt) := packetBase
                    contexts(index)(victim.asUInt) := pendingContext
                    words(index)(victim.asUInt) := io.memory.response.bits(64 * packet + 63, 64 * packet)
                    errors(index)(victim.asUInt) := io.memory.responseError(2 * packet + 1, 2 * packet)
                    pageFaults(index)(victim.asUInt) := io.memory.responsePageFault(2 * packet + 1, 2 * packet)
                    replace(index) := !victim
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
    val hits         = (0 until 2).map(i => valid(i) && !io.invalidate &&
        (io.pc === pcs(i) || io.pc === pcs(i) + 4.U))
    val reply        = io.memory.response.valid && pending
    val returning    = reply && !pendingStale && !io.invalidate
    val responseHit  = returning && (io.pc === pendingPc || io.pc === pendingPc + 4.U)
    val hit          = hits.reduce(_ || _) || responseHit
    val selectedPc   = Mux(hits(0), pcs(0), Mux(hits(1), pcs(1), pendingPc))
    val selectedData = Mux(hits(0), data(0), Mux(hits(1), data(1), io.memory.response.bits))
    val selectedErrors = Mux(hits(0), errors(0), Mux(hits(1), errors(1), io.memory.responseError))
    val selectedPageFaults = Mux(hits(0), pageFaults(0), Mux(hits(1), pageFaults(1), io.memory.responsePageFault))
    val first        = io.pc === selectedPc
    io.instruction0.valid := io.enable && hit
    io.instruction0.bits  := Mux(first, selectedData(31, 0), selectedData(63, 32))
    io.instructionFaults(0) := io.instruction0.valid && Mux(first, selectedErrors(0), selectedErrors(1))
    io.instructionPageFaults(0) := io.instruction0.valid &&
        Mux(first, selectedPageFaults(0), selectedPageFaults(1))
    // A partially consumed packet may join its successor, including a response arriving this cycle.
    // Match lane one independently: a redirected/stale response must never fill an unrelated lane.
    val nextPc          = io.pc + 4.U
    val nextHits        = (0 until 2).map(i => valid(i) && !io.invalidate &&
        (nextPc === pcs(i) || nextPc === pcs(i) + 4.U))
    val nextResponseHit = returning && (nextPc === pendingPc || nextPc === pendingPc + 4.U)
    val nextPacketPc    = Mux(nextHits(0), pcs(0), Mux(nextHits(1), pcs(1), pendingPc))
    val nextData        = Mux(nextHits(0), data(0), Mux(nextHits(1), data(1), io.memory.response.bits))
    val nextErrors = Mux(nextHits(0), errors(0), Mux(nextHits(1), errors(1), io.memory.responseError))
    val nextPageFaults = Mux(nextHits(0), pageFaults(0), Mux(nextHits(1), pageFaults(1),
        io.memory.responsePageFault))
    io.instruction1.valid := io.enable && hit && (nextHits.reduce(_ || _) || nextResponseHit)
    io.instruction1.bits  := Mux(nextPc === nextPacketPc, nextData(31, 0), nextData(63, 32))
    io.instructionFaults(1) := io.instruction1.valid &&
        Mux(nextPc === nextPacketPc, nextErrors(0), nextErrors(1))
    io.instructionPageFaults(1) := io.instruction1.valid &&
        Mux(nextPc === nextPacketPc, nextPageFaults(0), nextPageFaults(1))
    io.instructionFaultAddresses(0) := io.pc
    io.instructionFaultAddresses(1) := nextPc
    if (fetchWidth == 4) {
        for (lane <- 2 until 4) {
            val lanePc = io.pc + (4 * lane).U
            val laneHits = (0 until 2).map(i => valid(i) && !io.invalidate &&
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
            io.instructionFaults(lane) := io.instructions(lane).valid && Mux(low, laneErrors(0), laneErrors(1))
            io.instructionPageFaults(lane) := io.instructions(lane).valid && Mux(low, lanePages(0), lanePages(1))
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
