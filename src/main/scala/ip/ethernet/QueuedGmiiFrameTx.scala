package soc.ip.ethernet

import chisel3._
import chisel3.util._

/** Opt-in banked store-and-forward TX. Collection and serialization overlap;
  * each complete bank has exactly one producer/consumer owner. One synchronous
  * RAM write port and one read port support every bank; no combinational RAM.
  * Prefetch the next complete frame during IFG so saturated traffic has exactly
  * 12 idle byte-times at all three rates. A frame is never emitted before LAST.
  * Abort retires stored frames one per cycle and separately drains an in-flight
  * input frame through LAST; simultaneous abort counts cannot collapse to1.
  */
class QueuedGmiiFrameTx(maxFrameBytes: Int = 2048, frameSlots: Int = 2)
    extends EthernetFrameTransmitter(true) {
    require(maxFrameBytes >= 64 && maxFrameBytes <= 16384 && isPow2(maxFrameBytes))
    require(frameSlots >= 2 && frameSlots <= 8 && isPow2(frameSlots))
    private val wordBits = log2Ceil(maxFrameBytes / 4)
    private val slotBits = log2Ceil(frameSlots)
    private val lengthBits = log2Ceil(maxFrameBytes + 5)
    val buffer = SyncReadMem(frameSlots * maxFrameBytes / 4, UInt(32.W))
    val producer = RegInit(0.U(slotBits.W))
    val consumer = RegInit(0.U(slotBits.W))
    val occupied = RegInit(0.U(log2Ceil(frameSlots + 1).W))
    val lengths = Reg(Vec(frameSlots, UInt(lengthBits.W)))
    val publish = WireDefault(false.B)
    val release = WireDefault(false.B)
    when(publish =/= release) { occupied := Mux(publish, occupied + 1.U, occupied - 1.U) }
    when(publish) { producer := producer + 1.U }
    when(release) { consumer := consumer + 1.U }
    assert(occupied <= frameSlots.U, "TX frame-bank owner count overflow")
    assert(!publish || occupied < frameSlots.U, "TX published into an owned bank")
    assert(!release || occupied =/= 0.U, "TX released an unowned bank")
    val step = io.byteStep.get
    val abort = io.abort.get
    val collected = RegInit(0.U(lengthBits.W))
    val failed = RegInit(false.B)
    val failedAbort = RegInit(false.B)
    val dropStored = abort && occupied =/= 0.U
    val keep = io.frame.bits.keep
    val legalKeep = keep === 1.U || keep === 3.U || keep === 7.U || keep === 15.U
    val nextLength = collected +& PopCount(keep)
    val malformed = !legalKeep || (!io.frame.bits.last && keep =/= 15.U) ||
        nextLength > maxFrameBytes.U || (io.frame.bits.last && io.frame.bits.bad) || abort
    io.frame.ready := !dropStored && (collected =/= 0.U || failed ||
        (occupied < frameSlots.U && (io.enable || abort)))
    val incomingEnd = io.frame.fire && io.frame.bits.last
    io.rejected := dropStored || (incomingEnd && (failed || malformed || nextLength < 14.U))
    io.aborted.get := dropStored || (incomingEnd && (abort || failedAbort))
    when(io.frame.fire) {
        when(!failed && !malformed && nextLength <= maxFrameBytes.U) {
            buffer.write(Cat(producer, (collected >> 2)(wordBits - 1, 0)), io.frame.bits.data)
        }
        collected := Mux(nextLength > (maxFrameBytes + 4).U, (maxFrameBytes + 4).U, nextLength)
        failed := failed || malformed
        failedAbort := failedAbort || abort
        when(io.frame.bits.last) {
            when(!failed && !malformed && nextLength >= 14.U) {
                lengths(producer) := nextLength
                publish := true.B
            }
            collected := 0.U
            failed := false.B
            failedAbort := false.B
        }
    }
    when(abort && collected =/= 0.U && !incomingEnd) { failed := true.B; failedAbort := true.B }
    val idle :: load :: prime :: preamble :: body :: fcs :: gap :: Nil = Enum(7)
    val state = RegInit(idle)
    val length = RegInit(0.U(lengthBits.W))
    val wireLength = Mux(length < 60.U, 60.U, length)
    val position = RegInit(0.U(lengthBits.W))
    val preambleIndex = RegInit(0.U(3.W))
    val fcsIndex = RegInit(0.U(2.W))
    val gapIndex = RegInit(0.U(4.W))
    val crc = RegInit("hffffffff".U(32.W))
    val checksum = RegInit(0.U(32.W))
    val currentWord = Reg(UInt(32.W))
    val nextWord = Reg(UInt(32.W))
    //0=not fetched,1=first synchronous result,2=second result,3=ready.
    val gapPrefetch = RegInit(0.U(2.W))
    val gapLoad = state === gap && gapPrefetch === 0.U && occupied =/= 0.U && !abort
    val gapPrime = state === gap && gapPrefetch === 1.U && !abort
    val following = (position >> 2) +& 2.U
    val bodyPrefetch = state === body && step && position < length && position(1, 0) === 3.U &&
        (following << 2) < length
    val prefetch = ((state === prime || gapPrime) && length > 4.U) || bodyPrefetch
    val readEnable = state === load || gapLoad || prefetch
    val readAddress = Mux(state === load || gapLoad, 0.U,
        Mux(state === prime || gapPrime, 1.U, following))
    val readWord = buffer.read(Cat(consumer, readAddress(wordBits - 1, 0)), readEnable)
    val nextValid = RegNext(prefetch, false.B)
    when(nextValid) { nextWord := readWord }
    when(state === idle && occupied =/= 0.U && !abort) { length := lengths(consumer); state := load }
    when(state === load) { state := prime }
    when(state === prime) {
        currentWord := readWord
        preambleIndex := 0.U
        position := 0.U
        crc := "hffffffff".U
        state := preamble
    }
    when(gapLoad) { length := lengths(consumer); gapPrefetch := 1.U }
    when(gapPrime) { currentWord := readWord; gapPrefetch := 2.U }
    when(state === gap && gapPrefetch === 2.U && !abort) { gapPrefetch := 3.U }
    io.gmiiEnable := (state === preamble || state === body || state === fcs) && !abort
    io.gmiiError := false.B
    val byte = Mux(position < length,
        (currentWord >> Cat(position(1, 0), 0.U(3.W)))(7, 0), 0.U(8.W))
    io.gmiiData := MuxLookup(state, 0.U(8.W))(Seq(
        preamble -> Mux(preambleIndex === 7.U, "hd5".U, "h55".U),
        body -> byte, fcs -> (checksum >> Cat(fcsIndex, 0.U(3.W)))(7, 0)))
    io.done := state === fcs && fcsIndex === 3.U && step && !abort
    io.bytes := wireLength
    io.busy := occupied =/= 0.U || collected =/= 0.U || failed || state =/= idle
    when(state === preamble && step) {
        when(preambleIndex === 7.U) { state := body }
            .otherwise { preambleIndex := preambleIndex + 1.U }
    }
    val nextCrc = EthernetCrc32.update(crc, byte, 1)
    when(state === body && step) {
        crc := nextCrc
        when(position === wireLength - 1.U) { checksum := ~nextCrc; fcsIndex := 0.U; state := fcs }
            .otherwise {
                position := position + 1.U
                when(position(1, 0) === 3.U && position + 1.U < length) { currentWord := nextWord }
            }
    }
    when(state === fcs && step) {
        when(fcsIndex === 3.U) { release := true.B; state := gap; gapIndex := 0.U; gapPrefetch := 0.U }
            .otherwise { fcsIndex := fcsIndex + 1.U }
    }
    when(state === gap && step) {
        when(gapIndex === 11.U) {
            when(gapPrefetch === 3.U && !abort) {
                state := preamble
                position := 0.U
                preambleIndex := 0.U
                crc := "hffffffff".U
            }.otherwise { state := idle }
            gapPrefetch := 0.U
        }.otherwise { gapIndex := gapIndex + 1.U }
    }
    when(abort) {
        gapPrefetch := 0.U
        // Invalidate speculative read-valid state as well as prefetch metadata;
        // otherwise a late RAM result could resurrect a discarded next bank.
        nextValid := false.B
        when(dropStored) {
            release := true.B
            when(state =/= gap) { state := gap; gapIndex := 0.U }
        }
    }
}
