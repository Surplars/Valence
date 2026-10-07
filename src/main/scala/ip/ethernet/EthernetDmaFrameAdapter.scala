package soc.ip.ethernet

import chisel3._
import chisel3.util._
import soc.ip.dma.EthernetAxisWord

/** Single-clock adapter for the existing Valence DMA's narrow PG138 subset.
  * Does not change its descriptor, coherent memory, completion or four-stream
  * ABI. TX consumes exactly TAG A0000000 + five zero APP words before data.
  * Invalid controls mark the final native beat bad; TX frame engine drops it.
  * RX emits data then six status words, with true forwarded byte count in APP4.
  * Not a complete PG138 implementation: no checksum/VLAN/multicast metadata.
  * Complete frame/status ownership must cross clock domains in an outer wrapper.
  */
class EthernetDmaFrameAdapter(managed: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val txData = Flipped(Decoupled(new EthernetAxisWord))
        val txControl = Flipped(Decoupled(new EthernetAxisWord))
        val rxData = Decoupled(new EthernetAxisWord)
        val rxStatus = Decoupled(new EthernetAxisWord)
        val txFrame = Decoupled(new EthernetFrameBeat(4))
        val rxFrame = Flipped(Decoupled(new EthernetFrameBeat(4)))
        val stopNewTx = if (managed) Some(Input(Bool())) else None
        val txIdle = Output(Bool())
        val rxIdle = Output(Bool())
    })
    val controlPhase = RegInit(true.B)
    val controlIndex = RegInit(0.U(3.W))
    val controlBad = RegInit(false.B)
    io.txControl.ready := controlPhase && (!io.stopNewTx.getOrElse(false.B) || controlIndex =/= 0.U)
    when(io.txControl.fire) {
        val expected = Mux(controlIndex === 0.U, "ha0000000".U(32.W), 0.U(32.W))
        controlBad := controlBad || controlIndex > 5.U || io.txControl.bits.keep =/= 15.U ||
            io.txControl.bits.data =/= expected || io.txControl.bits.last =/= (controlIndex === 5.U)
        when(io.txControl.bits.last) { controlPhase := false.B }
        when(controlIndex < 6.U) { controlIndex := controlIndex + 1.U }
    }
    io.txFrame.valid := !controlPhase && io.txData.valid
    io.txData.ready := !controlPhase && io.txFrame.ready
    io.txFrame.bits.data := io.txData.bits.data
    io.txFrame.bits.keep := io.txData.bits.keep
    io.txFrame.bits.last := io.txData.bits.last
    io.txFrame.bits.bad := controlBad && io.txData.bits.last
    when(io.txFrame.fire && io.txFrame.bits.last) {
        controlPhase := true.B
        controlIndex := 0.U
        controlBad := false.B
    }
    val statusBusy = RegInit(false.B)
    val statusIndex = RegInit(0.U(3.W))
    val bytes = RegInit(0.U(16.W))
    val bad = RegInit(false.B)
    val resultLength = RegInit(0.U(16.W))
    val resultBad = RegInit(false.B)
    io.txIdle := controlPhase && controlIndex === 0.U && !io.txFrame.valid
    io.rxIdle := !statusBusy && bytes === 0.U && !io.rxFrame.valid
    io.rxFrame.ready := !statusBusy && io.rxData.ready
    io.rxData.valid := !statusBusy && io.rxFrame.valid
    io.rxData.bits.data := io.rxFrame.bits.data
    io.rxData.bits.keep := io.rxFrame.bits.keep
    io.rxData.bits.last := io.rxFrame.bits.last
    val keep = io.rxFrame.bits.keep
    val keepLegal = keep === 1.U || keep === 3.U || keep === 7.U || keep === 15.U
    val nextBytes = bytes +& PopCount(keep)
    val malformed = !keepLegal || (!io.rxFrame.bits.last && keep =/= 15.U) ||
        nextBytes > 65535.U || (io.rxFrame.bits.last && io.rxFrame.bits.bad)
    when(io.rxFrame.fire) {
        bytes := Mux(nextBytes > 65535.U, 65535.U, nextBytes)
        bad := bad || malformed
        when(io.rxFrame.bits.last) {
            resultLength := Mux(nextBytes > 65535.U, 65535.U, nextBytes)
            resultBad := bad || malformed
            statusBusy := true.B
            statusIndex := 0.U
            bytes := 0.U
            bad := false.B
        }
    }
    io.rxStatus.valid := statusBusy
    io.rxStatus.bits.keep := 15.U
    io.rxStatus.bits.last := statusIndex === 5.U
    io.rxStatus.bits.data := MuxLookup(statusIndex, 0.U(32.W))(Seq(
        0.U -> "h50000000".U, 3.U -> Mux(resultBad, 128.U, 64.U), 5.U -> resultLength))
    when(io.rxStatus.fire) {
        when(statusIndex === 5.U) { statusBusy := false.B }
            .otherwise { statusIndex := statusIndex + 1.U }
    }
}
