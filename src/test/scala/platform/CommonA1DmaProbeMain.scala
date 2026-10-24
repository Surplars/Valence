package platform

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.platform._

/** Existing real memory-copy DMA, not a synthetic coherent master. */
class A1DmaProbeFabric(p: CommonCpuTilePortParams, words: Int)
    extends CommonMachineFabric(boundary = p,
        features = CommonPlatformFeatures(ethernetControl = false, networkDma = false,
            jtagDownload = false, clockManagement = false), ramBytes = 65536,
        externalDdr = false, romWords = words, programmable = true,
        externalUart = false, ramResponseDelay = 7) {
    val dmaActive = IO(Output(Bool()))
    val dmaIrq = IO(Output(Bool()))
    val dmaRequests = IO(Output(UInt(32.W)))
    val dmaResponses = IO(Output(UInt(32.W)))
    val requests = RegInit(0.U(32.W)); val responses = RegInit(0.U(32.W))
    when(dma.io.memory.request.fire) { requests := requests + 1.U }
    when(dma.io.memory.response.fire) { responses := responses + 1.U }
    dmaActive := dma.io.active; dmaIrq := dma.io.irq
    dmaRequests := requests; dmaResponses := responses
}
class CommonA1DmaProbeFixture extends CommonA1RuntimeCdcFixture(256, testTimer = true) {
    override def makeFabric(): CommonMachineFabric = new A1DmaProbeFabric(boundary, testRomWords)
    val trapCause = IO(Output(UInt(64.W)))
    trapCause := tile.io.trap.bits.cause
    val holdProbeResponse = IO(Input(Bool())) // Test stimulus in CPU domain.
    val probeBlocked = IO(Output(Bool()))
    val probes = IO(Output(UInt(32.W)))
    val dirtyProbeBeats = IO(Output(UInt(32.W)))
    val dmaActive = IO(Output(Bool()))
    val dmaIrq = IO(Output(Bool()))
    val dmaRequests = IO(Output(UInt(32.W)))
    val dmaResponses = IO(Output(UInt(32.W)))
    val actual = fabric.asInstanceOf[A1DmaProbeFabric]
    dmaActive := actual.dmaActive; dmaIrq := actual.dmaIrq
    dmaRequests := actual.dmaRequests; dmaResponses := actual.dmaResponses
    val c = tile.io.bus.coherent(1).c
    val blocked = holdProbeResponse && c.bits.opcode === 5.U
    crossing.cpu.coherent(1).c.valid := c.valid && !blocked
    c.ready := crossing.cpu.coherent(1).c.ready && !blocked
    probeBlocked := c.valid && blocked
    withClockAndReset(cpuClock, tileReset) {
        val requests = RegInit(0.U(32.W)); val responses = RegInit(0.U(32.W))
        when(tile.io.bus.coherent(1).b.fire) { requests := requests + 1.U }
        when(c.fire && c.bits.opcode === 5.U) { responses := responses + 1.U }
        probes := requests; dirtyProbeBeats := responses
    }
}
object CommonA1DmaProbeMain extends App {
    ChiselStage.emitSystemVerilogFile(new CommonA1DmaProbeFixture, Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
