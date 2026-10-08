package soc.ip.ethernet

import chisel3._
import chisel3.util._

/** Shared transmit contract; optional rate ports preserve legacy elaboration. */
class GmiiFrameTxPort(rateAdaptation: Boolean) extends Bundle {
    val frame = Flipped(Decoupled(new EthernetFrameBeat(4)))
    val enable = Input(Bool())
    val byteStep = if (rateAdaptation) Some(Input(Bool())) else None
    val abort = if (rateAdaptation) Some(Input(Bool())) else None
    val aborted = if (rateAdaptation) Some(Output(Bool())) else None
    val gmiiData = Output(UInt(8.W))
    val gmiiEnable = Output(Bool())
    val gmiiError = Output(Bool())
    val busy = Output(Bool())
    val done = Output(Bool())
    val rejected = Output(Bool())
    val bytes = Output(UInt(16.W))
}

abstract class EthernetFrameTransmitter(rateAdaptation: Boolean) extends Module {
    val io = IO(new GmiiFrameTxPort(rateAdaptation))
}

/** Single-buffer store-and-forward transmitter. The default is byte-wide1G;
  * opt-in rate adaptation advances preamble/body/FCS/IFG only on byteStep.
  * Malformed keep/short-header/oversize/bad frames drain to LAST atomically.
  */
class GmiiFrameTx(maxFrameBytes: Int = 2048, rateAdaptation: Boolean = false)
    extends EthernetFrameTransmitter(rateAdaptation) {
    require(maxFrameBytes >= 64 && maxFrameBytes <= 16384 && isPow2(maxFrameBytes))
    private val indexBits = log2Ceil(maxFrameBytes / 4)
    private val lengthBits = log2Ceil(maxFrameBytes + 5)
    val buffer = SyncReadMem(maxFrameBytes / 4, UInt(32.W))
    val collect :: load :: prime :: preamble :: body :: fcs :: gap :: Nil = Enum(7)
    val state = RegInit(collect)
    val collected = RegInit(0.U(lengthBits.W))
    val failed = RegInit(false.B)
    val failedAbort = if (rateAdaptation) Some(RegInit(false.B)) else None
    val step = io.byteStep.getOrElse(true.B)
    val abort = io.abort.getOrElse(false.B)
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
    val keep = io.frame.bits.keep
    val keepLegal = keep === 1.U || keep === 3.U || keep === 7.U || keep === 15.U
    val nextLength = collected +& PopCount(keep)
    val malformed = !keepLegal || (!io.frame.bits.last && keep =/= 15.U) ||
        nextLength > maxFrameBytes.U || (io.frame.bits.last && io.frame.bits.bad) || abort
    io.frame.ready := state === collect && (io.enable || collected =/= 0.U || failed || abort)
    io.busy := state =/= collect || collected =/= 0.U || failed
    io.done := state === fcs && fcsIndex === 3.U && step && !abort
    io.rejected := io.frame.fire && io.frame.bits.last &&
        (failed || malformed || nextLength < 14.U)
    io.bytes := wireLength
    io.aborted.foreach(_ := io.frame.fire && io.frame.bits.last && (abort || failedAbort.get))
    when(io.frame.fire) {
        when(nextLength <= maxFrameBytes.U && !failed && !malformed) {
            buffer.write((collected >> 2)(indexBits - 1, 0), io.frame.bits.data)
        }
        collected := Mux(nextLength > (maxFrameBytes + 4).U, (maxFrameBytes + 4).U, nextLength)
        failed := failed || malformed
        failedAbort.foreach(_ := failedAbort.get || abort)
        when(io.frame.bits.last) {
            when(!failed && !malformed && nextLength >= 14.U) {
                length := nextLength
                state := load
            }
            collected := 0.U
            failed := false.B
            failedAbort.foreach(_ := false.B)
        }
    }
    // Prime two words before SFD. At each word boundary consume the prefetched
    // word and launch the following synchronous read; nextWord captures it on
    // the next cycle, three byte-times before it is needed. No wire underflow.
    val following = (position >> 2) +& 2.U
    val prefetch = (state === prime && length > 4.U) ||
        (state === body && step && position < length && position(1, 0) === 3.U &&
            (following << 2) < length)
    val readEnable = state === load || prefetch
    val readAddress = Mux(state === load, 0.U, Mux(state === prime, 1.U, following))
    val readWord = buffer.read(readAddress(indexBits - 1, 0), readEnable)
    val nextValid = RegNext(prefetch, false.B)
    when(nextValid) { nextWord := readWord }
    when(state === load) { state := prime }
    when(state === prime) {
        currentWord := readWord
        preambleIndex := 0.U
        position := 0.U
        crc := "hffffffff".U
        state := preamble
    }
    io.gmiiEnable := (state === preamble || state === body || state === fcs) && !abort
    io.gmiiError := false.B
    val byte = Mux(position < length,
        (currentWord >> Cat(position(1, 0), 0.U(3.W)))(7, 0), 0.U(8.W))
    io.gmiiData := MuxLookup(state, 0.U(8.W))(Seq(
        preamble -> Mux(preambleIndex === 7.U, "hd5".U, "h55".U),
        body -> byte, fcs -> (checksum >> Cat(fcsIndex, 0.U(3.W)))(7, 0)))
    when(state === preamble && step) {
        when(preambleIndex === 7.U) { state := body }
            .otherwise { preambleIndex := preambleIndex + 1.U }
    }
    val nextCrc = EthernetCrc32.update(crc, byte, 1)
    when(state === body && step) {
        crc := nextCrc
        when(position === wireLength - 1.U) {
            checksum := ~nextCrc
            fcsIndex := 0.U
            state := fcs
        }.otherwise {
            position := position + 1.U
            when(position(1, 0) === 3.U && position + 1.U < length) { currentWord := nextWord }
        }
    }
    when(state === fcs && step) {
        when(fcsIndex === 3.U) { state := gap; gapIndex := 0.U }
            .otherwise { fcsIndex := fcsIndex + 1.U }
    }
    when(state === gap && step) {
        when(gapIndex === 11.U) { state := collect }
            .otherwise { gapIndex := gapIndex + 1.U }
    }
    if (rateAdaptation) {
        // Cancel only the incomplete/unsent TX frame; no FIFO pointer or DMA
        // ownership is reset. Already admitted native beats drain through LAST.
        when(abort && state === collect && collected =/= 0.U && !(io.frame.fire && io.frame.bits.last)) {
            failed := true.B
            failedAbort.get := true.B
        }
        when(abort && state =/= collect && state =/= gap) {
            state := gap
            gapIndex := 0.U
            io.rejected := true.B
            io.aborted.get := true.B
        }
    }
}
