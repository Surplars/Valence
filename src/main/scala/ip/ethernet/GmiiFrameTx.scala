package soc.ip.ethernet

import chisel3._
import chisel3.util._

/** Single TX clock, 1G/full-duplex only. Store a complete native 32-bit frame
  * before generating an uninterrupted GMII burst. Insert 7x55/D5, zero padding
  * to 60 body bytes, reflected FCS and >=12 idle byte-times. Input excludes FCS.
  * Malformed keep/short-header/oversize/bad frames drain to LAST without emission.
  * No PHY, collision/pause, 10/100 clock-enable or CDC implementation here.
  */
class GmiiFrameTx(maxFrameBytes: Int = 2048) extends Module {
    require(maxFrameBytes >= 64 && maxFrameBytes <= 16384 && isPow2(maxFrameBytes))
    val io = IO(new Bundle {
        val frame = Flipped(Decoupled(new EthernetFrameBeat(4)))
        val enable = Input(Bool())
        val gmiiData = Output(UInt(8.W))
        val gmiiEnable = Output(Bool())
        val gmiiError = Output(Bool())
        val busy = Output(Bool())
        val done = Output(Bool())
        val rejected = Output(Bool())
        val bytes = Output(UInt(16.W))
    })
    private val indexBits = log2Ceil(maxFrameBytes / 4)
    private val lengthBits = log2Ceil(maxFrameBytes + 5)
    val buffer = SyncReadMem(maxFrameBytes / 4, UInt(32.W))
    val collect :: load :: prime :: preamble :: body :: fcs :: gap :: Nil = Enum(7)
    val state = RegInit(collect)
    val collected = RegInit(0.U(lengthBits.W))
    val failed = RegInit(false.B)
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
        nextLength > maxFrameBytes.U || (io.frame.bits.last && io.frame.bits.bad)
    io.frame.ready := state === collect && (io.enable || collected =/= 0.U || failed)
    io.busy := state =/= collect || collected =/= 0.U || failed
    io.done := state === fcs && fcsIndex === 3.U
    io.rejected := io.frame.fire && io.frame.bits.last &&
        (failed || malformed || nextLength < 14.U)
    io.bytes := wireLength
    when(io.frame.fire) {
        when(nextLength <= maxFrameBytes.U && !failed && !malformed) {
            buffer.write((collected >> 2)(indexBits - 1, 0), io.frame.bits.data)
        }
        collected := Mux(nextLength > (maxFrameBytes + 4).U, (maxFrameBytes + 4).U, nextLength)
        failed := failed || malformed
        when(io.frame.bits.last) {
            when(!failed && !malformed && nextLength >= 14.U) {
                length := nextLength
                state := load
            }
            collected := 0.U
            failed := false.B
        }
    }
    // Prime two words before SFD. At each word boundary consume the prefetched
    // word and launch the following synchronous read; nextWord captures it on
    // the next cycle, three byte-times before it is needed. No wire underflow.
    val following = (position >> 2) +& 2.U
    val prefetch = (state === prime && length > 4.U) ||
        (state === body && position < length && position(1, 0) === 3.U &&
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
    io.gmiiEnable := state === preamble || state === body || state === fcs
    io.gmiiError := false.B
    val byte = Mux(position < length,
        (currentWord >> Cat(position(1, 0), 0.U(3.W)))(7, 0), 0.U(8.W))
    io.gmiiData := MuxLookup(state, 0.U(8.W))(Seq(
        preamble -> Mux(preambleIndex === 7.U, "hd5".U, "h55".U),
        body -> byte, fcs -> (checksum >> Cat(fcsIndex, 0.U(3.W)))(7, 0)))
    when(state === preamble) {
        when(preambleIndex === 7.U) { state := body }
            .otherwise { preambleIndex := preambleIndex + 1.U }
    }
    val nextCrc = EthernetCrc32.update(crc, byte, 1)
    when(state === body) {
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
    when(state === fcs) {
        when(fcsIndex === 3.U) { state := gap; gapIndex := 0.U }
            .otherwise { fcsIndex := fcsIndex + 1.U }
    }
    when(state === gap) {
        when(gapIndex === 11.U) { state := collect }
            .otherwise { gapIndex := gapIndex + 1.U }
    }
}
