package soc.core.inorder

import chisel3._
import chisel3.util._

/** Optional FPGA IF boundary: one parcel owner, with same-edge response/request
  * turnover and a registered response when stalled. An already-authorized word
  * may supply more parcels in the SAME privilege/translation context. This
  * saves redundant cache/IT accesses; fetchSpan, not adjacency, is the proof.
  * Any context transition/FENCE.I kills reuse, including an in-flight fill.
  */
class FiveStageFetchWordCuts(p: FiveStageConfig) extends Module {
    require(p.withC && p.fpgaTimingCuts)
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(UInt(p.xlen.W)))
        val response = Decoupled(new FiveStageFetchResponse(p))
        val memoryRequest = Decoupled(new FiveStageDataRequest(p))
        val memoryResponse = Flipped(Decoupled(new FiveStageDataResponse(p)))
        val invalidate = Input(Bool())
        val bareTurnover = if (p.withH) Some(Input(Bool())) else None
        val addressCandidates = Output(Vec(2, UInt(p.xlen.W)))
        val candidateSecond = Output(Bool())
    })
    private val idle = 0; private val firstWait = 1; private val secondSend = 2
    private val secondWait = 3; private val reply = 4
    // Local phase equations, not BRAM data -> length mux -> binary FSM
    // encoder -> common state CE. Still exactly one existing parcel owner.
    private val phases = RegInit(VecInit(Seq(true.B, false.B, false.B, false.B, false.B)))
    private def in(phase: Int): Bool = phases(phase)
    val pc = Reg(UInt(p.xlen.W))
    val secondPc = Reg(UInt(p.xlen.W))
    val firstHalf = Reg(UInt(16.W))
    val result = Reg(new FiveStageFetchResponse(p))
    // Reuse is already fault-free. Clear its published guest metadata with one
    // owner bit instead of sending late parcel admission to every payload FF.
    val resultFromReuse = if (p.withH) Some(Reg(Bool())) else None
    val word = Reg(UInt(p.xlen.W))
    val wordClasses = if (p.cacheFetchPredecode) Some(Reg(UInt(8.W))) else None
    val wordAddress = Reg(UInt((p.xlen - log2Ceil(p.xlen / 8)).W))
    val wordValid = RegInit(false.B)
    val stale = RegInit(false.B)
    val offsetBits = log2Ceil(p.xlen / 8)
    val lanesPerWord = p.xlen / 16
    val pcLane = Reg(UInt(lanesPerWord.W))
    val waiting = in(firstWait) || in(secondWait)
    val directReply = Wire(Bool())
    val slot = in(idle) || ((in(reply) || directReply) && io.response.ready)
    // The owner phase selects payload independently of cache VALID/tag timing.
    // A completing return may supply the next parcel before word captures it.
    val reusableWord = Mux(waiting, io.memoryResponse.bits.data, word)
    val reusableClasses = Mux(waiting, io.memoryResponse.bits.parcelClasses.getOrElse(0.U(8.W)),
        wordClasses.getOrElse(0.U(8.W)))
    val returnedAddress = Mux(in(secondWait), secondPc, pc)(p.xlen - 1, offsetBits)
    val reusableAddress = Mux(waiting, returnedAddress, wordAddress)
    val reuseAuthorized = Mux(waiting,
        io.memoryResponse.bits.fetchSpan && !io.memoryResponse.bits.error &&
            !io.memoryResponse.bits.pageFault && !stale,
        wordValid)
    // While waiting, slot already proves the old response really completes.
    // Invalid/stale/partially-authorized returns never authorize fresh reuse.
    val reuse = reuseAuthorized && !io.invalidate &&
        reusableAddress === io.request.bits(p.xlen - 1, offsetBits)
    // A registered translation owner cannot admit the next memory request
    // while returning the previous word. Word reuse still turns over locally;
    // a different word holds its offer until that translation owner retires.
    val holdMemoryOffer = (p.fastInstructionTranslation && (p.withSv39 || p.pmpEntries > 0)).B &&
        waiting && !io.bareTurnover.getOrElse(false.B)
    io.request.ready := slot && (reuse || (!holdMemoryOffer && io.memoryRequest.ready))
    io.memoryRequest.valid := in(secondSend) || (slot && !holdMemoryOffer && io.request.valid && !reuse)
    io.memoryRequest.bits := 0.U.asTypeOf(new FiveStageDataRequest(p))
    io.memoryRequest.bits.address := Mux(in(secondSend), secondPc, io.request.bits)
    io.addressCandidates(0) := io.request.bits
    io.addressCandidates(1) := secondPc
    io.candidateSecond := in(secondSend)
    io.memoryRequest.bits.size := 1.U
    io.memoryResponse.ready := in(firstWait) || in(secondWait)
    io.response.valid := in(reply) || directReply
    io.response.bits := result
    resultFromReuse.foreach(reused => io.response.bits.guest.get :=
        Mux(reused, 0.U.asTypeOf(new I1GuestFault), result.guest.get))

    // Classification determines whether the old parcel is complete. It never
    // selects a wide data source; source ownership above is registered phase.
    def standardWords(data: UInt): UInt = VecInit((0 until p.xlen / 8 by 2).map { offset =>
        // Standard32 means low2=11 AND next3!=111. Do not decode long then
        // feed a second compressed/long priority tree after the word mux.
        data(offset * 8 + 1, offset * 8).andR &&
            !data(offset * 8 + 4, offset * 8 + 2).andR
    }).asUInt
    def needsSecond(data: UInt, classes: UInt, selected: UInt, span: Bool, error: Bool): Bool = {
        val standard = if (p.cacheFetchPredecode) classes(lanesPerWord - 1, 0) else standardWords(data)
        !error && (((standard & selected).orR && !span) ||
            (standard(lanesPerWord - 1) && selected(lanesPerWord - 1)))
    }
    val reuseLane = UIntToOH(io.request.bits(offsetBits - 1, 1), lanesPerWord)
    val returnedClasses = io.memoryResponse.bits.parcelClasses.getOrElse(0.U(8.W))
    val memorySplit = needsSecond(io.memoryResponse.bits.data, returnedClasses, pcLane,
        io.memoryResponse.bits.fetchSpan, io.memoryResponse.bits.error)
    val reuseSplit = needsSecond(reusableWord, reusableClasses, reuseLane, true.B, false.B)
    directReply := io.memoryResponse.valid && (in(secondWait) || (in(firstWait) && !memorySplit))
    def firstParcel(data: UInt, classes: UInt, selectedLane: UInt): (UInt, Bool, UInt) = {
        // Decode fixed halfword windows BEFORE selecting the parcel. Avoid
        // SRAM -> 64-bit byte barrel -> length decode -> instruction mux.
        // The existing aligned-PC contract permits halfword, not byte, lanes.
        val lanes = (0 until p.xlen / 8 by 2).map { offset =>
            val shifted = (data >> (8 * offset)).pad(32)
            val compressed = if (p.cacheFetchPredecode) classes(4 + offset / 2) else shifted(1, 0) =/= 3.U
            val selected = selectedLane(offset / 2)
            val standard = if (p.cacheFetchPredecode) classes(offset / 2)
                else shifted(1, 0).andR && !shifted(4, 2).andR
            (selected, standard, compressed, shifted(15, 0), shifted(31, 16))
        }
        val compressed = Mux1H(lanes.map(v => v._1 -> v._3))
        val lower = Mux1H(lanes.map(v => v._1 -> v._4))
        val upper = Mux1H(lanes.map(v => (v._1 && v._2) -> v._5))
        (Cat(upper, lower), compressed, lower)
    }
    def secondParcel(data: UInt, enable: Bool = true.B): UInt = {
        val nextLane = Cat(pcLane(lanesPerWord - 2, 0), pcLane(lanesPerWord - 1))
        Mux1H((0 until p.xlen / 8 by 2).map { offset =>
            (nextLane(offset / 2) && enable) -> data(8 * offset + 15, 8 * offset)
        })
    }
    def acceptFirst(data: UInt, classes: UInt, selectedLane: UInt, error: Bool, pageFault: Bool): Unit = {
        val (instruction, compressed, _) = firstParcel(data, classes, selectedLane)
        // Retained as a held-reply oracle. Synthesis drops this shadow
        // instruction register, not the actual response/permission registers.
        result.instruction := instruction
        result.compressed := compressed && !error
        result.error := error
        result.pageFault := pageFault
        result.secondHalfFault := false.B
    }
    val registeredFirst = firstParcel(word, wordClasses.getOrElse(0.U(8.W)), pcLane)
    val returnedFirst = firstParcel(io.memoryResponse.bits.data, returnedClasses, pcLane)
    // Early phase, not late return VALID, selects both the data and status.
    // If downstream stalls, the existing registers retain this exact reply.
    // Qualify fixed windows with the registered phase before selecting data.
    // Late BRAM length bits then pass one OR reduction, instead of a nested
    // returned/held and first/second four-way instruction mux.
    val returnFirst = firstParcel(io.memoryResponse.bits.data, returnedClasses,
        pcLane & Fill(lanesPerWord, in(firstWait)))._1
    val holdFirst = firstParcel(word, wordClasses.getOrElse(0.U(8.W)),
        pcLane & Fill(lanesPerWord, !waiting && !result.secondHalfFault))._1
    val returnSecond = Cat(secondParcel(io.memoryResponse.bits.data, in(secondWait)),
        firstHalf & Fill(16, in(secondWait)))
    val heldSecond = !waiting && result.secondHalfFault
    val holdSecond = Cat(secondParcel(word, heldSecond), firstHalf & Fill(16, heldSecond))
    io.response.bits.instruction := returnFirst | holdFirst | returnSecond | holdSecond
    when(waiting) {
        io.response.bits.compressed := in(firstWait) && returnedFirst._2 && !io.memoryResponse.bits.error
        io.response.bits.error := io.memoryResponse.bits.error
        io.response.bits.pageFault := io.memoryResponse.bits.pageFault
        io.response.bits.guest.foreach(_ := io.memoryResponse.bits.guest.get)
        io.response.bits.secondHalfFault := in(secondWait)
    }
    when(in(secondSend)) { firstHalf := registeredFirst._3 }
    // Prepare raw payload throughout the retained wait phase. A return can
    // bypass to the consumer, or the existing word/result registers hold it.
    // Real response/turnover controls ownership, not the wide word capture CE.
    when(in(firstWait) || in(secondWait)) {
        resultFromReuse.foreach(_ := false.B)
        val data = io.memoryResponse.bits
        result.guest.foreach(_ := data.guest.get)
        // A wait phase owns this existing word storage. Prepare even before
        // VALID, but ONLY the real response edge advances phase/wordValid.
        word := data.data
        wordClasses.foreach(_ := returnedClasses)
        when(in(firstWait)) {
            acceptFirst(data.data, returnedClasses, pcLane, data.error, data.pageFault)
            result.guest.foreach(_ := data.guest.get)
        }.otherwise {
            val half = secondParcel(data.data)
            result.instruction := Cat(half, firstHalf)
            result.compressed := false.B
            result.error := data.error
            result.pageFault := data.pageFault
            result.secondHalfFault := true.B
        }
    }
    // New-owner metadata wins over old-return preparation on a turnover edge.
    // word itself still captures the return, including when the new owner reuses it.
    when(io.request.fire) {
        pc := io.request.bits
        pcLane := reuseLane
        secondPc := I1TimingMath.incrementPowerOfTwo(io.request.bits, 1, 8)
        stale := io.invalidate
        when(reuse) {
            acceptFirst(reusableWord, reusableClasses, reuseLane, false.B, false.B)
            resultFromReuse.foreach(_ := true.B)
        }
    }
    when(io.memoryResponse.fire) {
        val data = io.memoryResponse.bits
        val address = Mux(in(secondWait), secondPc, pc)
        // Error, a partial-word PMP grant or killed context never fills reuse.
        wordValid := !data.error && data.fetchSpan && !stale && !io.invalidate
        when(!data.error && data.fetchSpan && !stale && !io.invalidate) {
            wordAddress := address(p.xlen - 1, offsetBits)
        }
    }
    val accepted = io.request.fire
    val reused = accepted && reuse
    val firstReturned = in(firstWait) && io.memoryResponse.valid
    val secondReturned = in(secondWait) && io.memoryResponse.valid
    phases(idle) := (in(idle) && !accepted) || (io.response.fire && !accepted)
    phases(firstWait) := (in(firstWait) && !io.memoryResponse.valid) || (accepted && !reuse)
    phases(secondSend) := (in(secondSend) && !io.memoryRequest.ready) ||
        (firstReturned && memorySplit) || (reused && reuseSplit)
    phases(secondWait) := (in(secondWait) && !io.memoryResponse.valid) ||
        (in(secondSend) && io.memoryRequest.ready)
    phases(reply) := ((in(reply) || (firstReturned && !memorySplit) || secondReturned) &&
        !io.response.ready) || (reused && !reuseSplit)
    when(io.invalidate) { wordValid := false.B; stale := true.B }
    when(!reset.asBool) {
        when(in(reply)) {
            assert(io.response.bits.instruction === result.instruction,
                "raw-word retiming changed the authorized parcel response")
        }
        if (p.cacheFetchPredecode) when(io.memoryResponse.fire && !io.memoryResponse.bits.error) {
            assert(returnedClasses === I1InstructionPredecode.classify(io.memoryResponse.bits.data),
                "aligner parcel metadata has no matching instruction word")
        }
        assert(PopCount(phases) === 1.U, "fetch phase lost its sole parcel owner")
        assert(!io.memoryResponse.valid || in(firstWait) || in(secondWait),
            "registered C response has no parcel owner")
        assert(!io.request.fire || !io.request.bits(0), "odd instruction PC")
        when(io.request.fire && io.memoryResponse.fire) {
            assert(io.response.fire, "C turnover must complete the old owner before replacing it")
        }
    }
}
