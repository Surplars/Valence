package soc.core.inorder

import chisel3._
import chisel3.util._

/** Optional FPGA IF boundary: one parcel owner and one registered instruction
  * response, never a second outstanding request. An already-authorized word
  * may supply more parcels in the SAME privilege/translation context. This
  * saves redundant cache/IT accesses; fetchSpan, not adjacency, is the proof.
  * Any context transition/FENCE.I kills reuse, including an in-flight fill.
  */
class FiveStageFetchWordCuts(p: FiveStageConfig) extends Module {
    require(p.withC && p.fpgaTimingCuts)
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(UInt(p.xlen.W)))
        val response = Decoupled(new FiveStageFetchResponse)
        val memoryRequest = Decoupled(new FiveStageDataRequest(p))
        val memoryResponse = Flipped(Decoupled(new FiveStageDataResponse(p)))
        val invalidate = Input(Bool())
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
    val result = Reg(new FiveStageFetchResponse)
    val word = Reg(UInt(p.xlen.W))
    val wordClasses = if (p.cacheFetchPredecode) Some(Reg(UInt(8.W))) else None
    val wordAddress = Reg(UInt((p.xlen - log2Ceil(p.xlen / 8)).W))
    val wordValid = RegInit(false.B)
    val stale = RegInit(false.B)
    val offsetBits = log2Ceil(p.xlen / 8)
    val lanesPerWord = p.xlen / 16
    val pcLane = Reg(UInt(lanesPerWord.W))
    val slot = in(idle) || (in(reply) && io.response.ready)
    val reuse = wordValid && !io.invalidate &&
        wordAddress === io.request.bits(p.xlen - 1, offsetBits)
    io.request.ready := slot && (reuse || io.memoryRequest.ready)
    io.memoryRequest.valid := in(secondSend) || (slot && io.request.valid && !reuse)
    io.memoryRequest.bits := 0.U.asTypeOf(new FiveStageDataRequest(p))
    io.memoryRequest.bits.address := Mux(in(secondSend), secondPc, io.request.bits)
    io.addressCandidates(0) := io.request.bits
    io.addressCandidates(1) := secondPc
    io.candidateSecond := in(secondSend)
    io.memoryRequest.bits.size := 1.U
    io.memoryResponse.ready := in(firstWait) || in(secondWait)
    io.response.valid := in(reply)
    io.response.bits := result

    // No response-valid/parcel classification/RAW cache data reaches a new
    // request's admission in this profile. Only registered reply/word state.
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
    val reuseSplit = needsSecond(word, wordClasses.getOrElse(0.U(8.W)), reuseLane, true.B, false.B)
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
    def secondParcel(data: UInt): UInt = {
        val nextLane = Cat(pcLane(lanesPerWord - 2, 0), pcLane(lanesPerWord - 1))
        Mux1H((0 until p.xlen / 8 by 2).map { offset =>
            nextLane(offset / 2) -> data(8 * offset + 15, 8 * offset)
        })
    }
    def acceptFirst(data: UInt, classes: UInt, selectedLane: UInt, error: Bool, pageFault: Bool): Unit = {
        val (instruction, compressed, _) = firstParcel(data, classes, selectedLane)
        // Retained as a cycle-by-cycle oracle. Synthesis drops this shadow
        // instruction register, not the actual response/permission registers.
        result.instruction := instruction
        result.compressed := compressed && !error
        result.error := error
        result.pageFault := pageFault
        result.secondHalfFault := false.B
    }
    // Re-time alignment across the EXISTING word register. BRAM returns now
    // capture raw data first; the same next-cycle reply aligns registered data.
    // No extra parcel owner, edge, cache access or instruction bubble.
    val registeredFirst = firstParcel(word, wordClasses.getOrElse(0.U(8.W)), pcLane)
    io.response.bits.instruction := Mux(result.secondHalfFault,
        Cat(secondParcel(word), firstHalf), registeredFirst._1)
    when(in(secondSend)) { firstHalf := registeredFirst._3 }
    when(io.request.fire) {
        pc := io.request.bits
        pcLane := reuseLane
        secondPc := I1TimingMath.incrementPowerOfTwo(io.request.bits, 1, 8)
        stale := io.invalidate
        when(reuse) { acceptFirst(word, wordClasses.getOrElse(0.U(8.W)), reuseLane, false.B, false.B) }
    }
    // Only the registered reply phase exposes result/firstHalf. Prepare the
    // existing payload registers throughout their retained wait phase; the
    // real response edge still alone advances ownership and validates data.
    // Cache tag/response VALID therefore does not enable every result bit.
    when(in(firstWait) || in(secondWait)) {
        val data = io.memoryResponse.bits
        // A wait phase owns this existing word storage. Prepare even before
        // VALID, but ONLY the real response edge advances phase/wordValid.
        word := data.data
        wordClasses.foreach(_ := returnedClasses)
        when(in(firstWait)) {
            acceptFirst(data.data, returnedClasses, pcLane, data.error, data.pageFault)
        }.otherwise {
            val half = secondParcel(data.data)
            result.instruction := Cat(half, firstHalf)
            result.compressed := false.B
            result.error := data.error
            result.pageFault := data.pageFault
            result.secondHalfFault := true.B
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
    phases(idle) := (in(idle) && !accepted) ||
        (in(reply) && io.response.ready && !accepted)
    phases(firstWait) := (in(firstWait) && !io.memoryResponse.valid) || (accepted && !reuse)
    phases(secondSend) := (in(secondSend) && !io.memoryRequest.ready) ||
        (firstReturned && memorySplit) || (reused && reuseSplit)
    phases(secondWait) := (in(secondWait) && !io.memoryResponse.valid) ||
        (in(secondSend) && io.memoryRequest.ready)
    phases(reply) := (in(reply) && !io.response.ready) ||
        (firstReturned && !memorySplit) || secondReturned || (reused && !reuseSplit)
    when(io.invalidate) { wordValid := false.B; stale := true.B }
    when(!reset.asBool) {
        when(io.response.valid) {
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
        assert(!(io.request.fire && io.memoryResponse.fire), "two C owners accepted on one edge")
    }
}
