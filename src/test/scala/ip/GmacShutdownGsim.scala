package ip

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.ip.bus.RegisterPort
import soc.ip.dma.{EthernetAxisWord, EthernetPacketDma}
import soc.ip.ethernet.ManagedGmac

/** Real managed MAC, CDC mailboxes/FIFOs, native adapter and packet DMA.
  * All clocks are deliberately aliased: this tests functional ownership and
  * backpressure, NOT independent-clock CDC, a physical gate, PHY or board.
  * Test-only gates delay the two RX streams without changing their payload.
  * DDR contents and completion timing belong to the independent C++ oracle.
  */
class GmacShutdownGsim extends Module {
    val io = IO(new Bundle {
        val gmac = Flipped(new RegisterPort)
        val dma = Flipped(new RegisterPort)
        val memory = new RegisterPort
        val gmiiRxData = Input(UInt(8.W))
        val gmiiRxValid = Input(Bool())
        val gmiiRxError = Input(Bool())
        val rxClockEnable = Input(Bool())
        val rxQuiesce = Input(Bool())
        val rxIsolate = Input(Bool())
        val rxWake = Output(Bool())
        val rxAck = Output(Bool())
        val holdData = Input(Bool())
        val holdStatus = Input(Bool())
        val rxDataValid = Output(Bool())
        val rxDataReady = Output(Bool())
        val rxData = Output(new EthernetAxisWord)
        val rxStatusValid = Output(Bool())
        val rxStatusReady = Output(Bool())
        val rxStatus = Output(new EthernetAxisWord)
        val dmaActive = Output(Bool())
        val gmiiTxEnable = Output(Bool())
        val gmiiTxError = Output(Bool())
    })
    val mac = Module(new ManagedGmac(hardwareClocks = false))
    val dma = Module(new EthernetPacketDma(ramBytes = 8192))
    mac.sourceClock := clock
    mac.rawTxClock := clock
    mac.rawRxClock := clock
    mac.commonReset := reset.asBool.asAsyncReset
    for (n <- 0 until 2) {
        mac.control(n).clockEnable := (if (n == 1) io.rxClockEnable else true.B)
        mac.control(n).quiesce := (if (n == 1) io.rxQuiesce else false.B)
        mac.control(n).isolate := (if (n == 1) io.rxIsolate else false.B)
        mac.control(n).allowAdmission := true.B
    }
    io.rxWake := mac.control(1).wake
    io.rxAck := mac.control(1).ack
    mac.registers <> io.gmac
    dma.io.control <> io.dma
    io.memory <> dma.io.memory
    mac.streams.txData <> dma.io.txData
    mac.streams.txControl <> dma.io.txControl
    dma.io.rxData.valid := mac.streams.rxData.valid && !io.holdData
    dma.io.rxData.bits := mac.streams.rxData.bits
    mac.streams.rxData.ready := dma.io.rxData.ready && !io.holdData
    dma.io.rxStatus.valid := mac.streams.rxStatus.valid && !io.holdStatus
    dma.io.rxStatus.bits := mac.streams.rxStatus.bits
    mac.streams.rxStatus.ready := dma.io.rxStatus.ready && !io.holdStatus
    io.rxDataValid := mac.streams.rxData.valid
    io.rxDataReady := mac.streams.rxData.ready
    io.rxData := mac.streams.rxData.bits
    io.rxStatusValid := mac.streams.rxStatus.valid
    io.rxStatusReady := mac.streams.rxStatus.ready
    io.rxStatus := mac.streams.rxStatus.bits
    io.dmaActive := dma.io.active
    mac.gmiiRxData := io.gmiiRxData
    mac.gmiiRxValid := io.gmiiRxValid
    mac.gmiiRxError := io.gmiiRxError
    mac.linkUp := true.B
    mac.mdioIn := true.B
    io.gmiiTxEnable := mac.gmiiTxEnable
    io.gmiiTxError := mac.gmiiTxError
}

object GmacShutdownGsimMain extends App {
    // Pinned GSIM duplicates derived AsyncReset aliases incorrectly. Only this
    // all-clock-aliased model samples reset on a step. Production RTL is intact.
    val fir = ChiselStage.emitCHIRRTL(new GmacShutdownGsim)
    val sampled = fir.replace("AsyncReset", "UInt<1>").replace("asUInt<1>(", "asUInt(")
    val output = os.Path(args.head, os.pwd)
    os.makeDir.all(output)
    os.write(output / "GmacShutdownGsim.fir", sampled)
}
