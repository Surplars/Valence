package soc.core.inorder

import chisel3._
import chisel3.util._

/** Single-hart/exclusive-writer physical RAM atomics, after VA/PMP and before the only D-cache.
  * Holds one owner across read/registered modify/real write ack. No posted result or response carry chain.
  * IF/PTW are read-only; live DMA/another write master requires a future system atomic/coherence contract.
  * Reservation is physical, exact address+size, independent of cache eviction. Clear on context/external events.
  */
class FiveStageAtomicMemory(p: FiveStageConfig) extends Module {
    require(p.withA)
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new FiveStageDataRequest(p)))
        val response = Decoupled(new FiveStageDataResponse(p))
        val memoryRequest = Decoupled(new FiveStageDataRequest(p))
        val memoryResponse = Flipped(Decoupled(new FiveStageDataResponse(p)))
        val invalidateReservation = Input(Bool())
        val reservationValid = Output(Bool())
        val registeredOwner = Output(Bool())
    })
    val idle :: bypass :: readSend :: readWait :: modify :: writeSend :: writeWait :: reply :: Nil = Enum(8)
    val state = RegInit(idle)
    io.registeredOwner := state =/= idle
    val saved = Reg(new FiveStageDataRequest(p))
    val result = Reg(new FiveStageDataResponse(p))
    val oldWord = Reg(UInt(p.xlen.W)); val updatedWord = Reg(UInt(p.xlen.W))
    val reserved = RegInit(false.B)
    val reservedAddress = Reg(UInt(p.physicalBits.W)); val reservedSize = Reg(UInt(2.W))
    val killed = RegInit(false.B)
    io.reservationValid := reserved
    val incoming = io.request.bits
    val lr = saved.atomicOperation === 2.U
    val sc = saved.atomicOperation === 3.U
    // Configured RAM endpoints are whole-line aligned; a naturally aligned W/D cannot cross them.
    val ram = incoming.address >= p.cacheableBase.U &&
        incoming.address < (p.cacheableBase + p.cacheableBytes).U
    val sizeLegal = incoming.size === 2.U || (p.xlen == 64).B && incoming.size === 3.U
    val operationLegal = Seq(0, 1, 2, 3, 4, 8, 12, 16, 20, 24, 28)
        .map(n => incoming.atomicOperation === n.U).reduce(_ || _)
    val aligned = (incoming.address(2, 0) & Mux(incoming.size === 3.U, 7.U, 3.U)) === 0.U
    val successfulSc = reserved && reservedAddress === incoming.address &&
        reservedSize === incoming.size && !io.invalidateReservation
    io.request.ready := state === idle && Mux(incoming.atomic, true.B, io.memoryRequest.ready)
    io.response.valid := state === reply || (state === bypass && io.memoryResponse.valid)
    io.response.bits := Mux(state === bypass, io.memoryResponse.bits, result)
    io.memoryRequest.valid := (state === idle && io.request.valid && !incoming.atomic) ||
        state === readSend || state === writeSend
    io.memoryRequest.bits := Mux(state === idle, incoming, saved)
    io.memoryRequest.bits.atomic := false.B; io.memoryRequest.bits.atomicOperation := 0.U
    when(state === readSend) {
        io.memoryRequest.bits.write := false.B
        io.memoryRequest.bits.data := 0.U; io.memoryRequest.bits.mask := 0.U
    }
    when(state === writeSend) {
        io.memoryRequest.bits.write := true.B
        io.memoryRequest.bits.data := Mux(sc, saved.data, updatedWord)
    }
    io.memoryResponse.ready := (state === bypass && io.response.ready) || state === readWait || state === writeWait
    when(io.request.fire) {
        saved := incoming; killed := io.invalidateReservation
        result.data := 0.U; result.error := false.B; result.pageFault := false.B; result.fetchSpan := false.B
        when(!incoming.atomic) {
            state := bypass
        }.elsewhen(!ram || !sizeLegal || !aligned || !operationLegal) {
            result.error := true.B; state := reply
        }.elsewhen(incoming.atomicOperation === 3.U) {
            when(successfulSc) { state := writeSend }.otherwise { result.data := 1.U; state := reply }
        }.otherwise { state := readSend }
        when(incoming.atomicOperation === 3.U && incoming.atomic) { reserved := false.B }
        when(incoming.write && reserved &&
            incoming.address(p.physicalBits - 1, log2Ceil(p.xlen / 8)) ===
                reservedAddress(p.physicalBits - 1, log2Ceil(p.xlen / 8))) { reserved := false.B }
        when(incoming.atomic && incoming.atomicOperation === 2.U) { reserved := false.B }
    }
    when(io.memoryRequest.fire && state === readSend) { state := readWait }
    when(io.memoryRequest.fire && state === writeSend) { state := writeWait }
    when(state === readWait && io.memoryResponse.fire) {
        oldWord := io.memoryResponse.bits.data
        result.data := io.memoryResponse.bits.data
        result.error := io.memoryResponse.bits.error
        when(io.memoryResponse.bits.error) { state := reply }
            .elsewhen(lr) {
                when(!killed && !io.invalidateReservation) {
                    reserved := true.B; reservedAddress := saved.address; reservedSize := saved.size
                }
                state := reply
            }.otherwise { state := modify }
    }
    val offset = saved.address(log2Ceil(p.xlen / 8) - 1, 0)
    val word = saved.size === 2.U
    // Admission guarantees natural W/D alignment. FPGA AMOs only choose the
    // lower/upper 32-bit lane; byte barrel shifters add no legal operation.
    val upperWord = if (p.xlen == 64) word && saved.address(2) else false.B
    def alignedOperand(value: UInt): UInt = if (p.fpgaTimingCuts) {
        if (p.xlen == 64) Mux(upperWord, value(63, 32).pad(64), value) else value
    } else value >> Cat(offset, 0.U(3.W))
    val oldShifted = alignedOperand(oldWord)
    val operandShifted = alignedOperand(saved.data)
    // W operations consume only the low result lane. Keep sign selection out
    // of the XLEN data operands and share one unsigned comparison for MIN/MAX.
    val left = oldShifted
    val right = operandShifted
    val unsignedLess = if (p.xlen == 64) {
        val low = left(31, 0) < right(31, 0)
        (!word && left(63, 32) < right(63, 32)) ||
            ((word || I1TimingMath.equal(left(63, 32), right(63, 32))) && low)
    } else left < right
    val leftSign = if (p.xlen == 64) Mux(word, left(31), left(63)) else left(31)
    val rightSign = if (p.xlen == 64) Mux(word, right(31), right(63)) else right(31)
    val signedLess = Mux(leftSign =/= rightSign, leftSign, unsignedLess)
    val combined = MuxLookup(saved.atomicOperation, right)(Seq(
        0.U -> (left + right), 1.U -> right, 4.U -> (left ^ right), 8.U -> (left | right),
        12.U -> (left & right), 16.U -> Mux(signedLess, left, right),
        20.U -> Mux(signedLess, right, left),
        24.U -> Mux(unsignedLess, left, right), 28.U -> Mux(unsignedLess, right, left)))
    when(state === modify) {
        updatedWord := (if (p.fpgaTimingCuts) {
            if (p.xlen == 64) Mux(upperWord, Cat(combined(31, 0), 0.U(32.W)), combined) else combined
        } else (combined << Cat(offset, 0.U(3.W)))(p.xlen - 1, 0))
        state := writeSend
    }
    when(state === writeWait && io.memoryResponse.fire) {
        result.data := Mux(sc, 0.U, oldWord); result.error := io.memoryResponse.bits.error; state := reply
    }
    when(io.response.fire) { state := idle }
    when(io.invalidateReservation) { reserved := false.B; when(state =/= idle) { killed := true.B } }
    when(!reset.asBool) {
        assert(!io.memoryResponse.valid || state === bypass || state === readWait || state === writeWait,
            "atomic backend response without owner")
        assert(!(state === bypass && saved.atomic), "atomic operation leaked into normal bypass")
    }
    // Physical caches/atomic memory and the host-only walker never create guest faults.
    io.response.bits.guest.foreach(_ := 0.U.asTypeOf(new I1GuestFault))

}
