package ip

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.ip.bus.RegisterPort
import soc.ip.clock.ManagedPeripheralBank
import soc.ip.dma.NetworkDmaConfig
import soc.ip.ethernet._

/** Only policy startup/poll WAIT intervals are shortened for a bounded native
  * simulation. The real MDIO 100 MHz / 1.25 MHz divider, full transactions,
  * page sequencing, two-poll debounce, and every other timeout are unchanged.
  * This is not a production elapsed-time or live-frequency-change witness.
  */
class ManagedRuntimeTestMac(config: NetworkDmaConfig, slots: Int)
    extends TriSpeedManagedGmac(hardwareClocks = false, networkDmaConfig = config,
        txFrameSlots = slots, runtimeAdmission = true, runtimeControlPark = true) {
    override def desiredName: String = "TriSpeedManagedGmac"
    override protected def buildPhyManager(): Rtl8211fPhyManager =
        new Rtl8211fPhyManager(100000000, startupCycles = 256, pollCycles = 512,
            runtimePark = true)
}

class ManagedRuntimeTestBank(config: NetworkDmaConfig, slots: Int)
    extends ManagedPeripheralBank(ManagedPeripheralTestConfig.params.copy(timeoutCycles = 65536),
        hardwareClocks = false, networkDmaConfig = config, triSpeedEthernet = true,
        triSpeedTxFrameSlots = slots, runtimeAdmission = true, runtimeControlPark = true) {
    override def desiredName: String = "ManagedPeripheralBank"
    override protected def buildTriSpeedMac(): TriSpeedManagedGmac =
        new ManagedRuntimeTestMac(config, slots)
}

/** Real managed bank and tri-speed control/packet owners with every clock running.
  * The bench drives the actual MDIO pins; no PHY/media/link bypass is provided.
  * Control park retains statistics while raw traffic can continue. It is not a
  * clock gate, DFS endpoint, four-class runtime ACK, or physical timing witness.
  * UART and CMU remain real and separately accessible, but are not silently
  * included in the MAC-only controlPark result. No CPU, DMA or DDR is modeled.
  */
class ManagedRuntimeControlFixture(config: NetworkDmaConfig, slots: Int) extends RawModule {
    val sourceClock = IO(Input(Clock()))
    val alwaysOnClock = IO(Input(Clock()))
    val rawUartClock = IO(Input(Clock()))
    val rawTxClock = IO(Input(Clock()))
    val rawRxClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val cmuRegisters = IO(Flipped(new RegisterPort))
    val uartRegisters = IO(Flipped(new RegisterPort))
    val gmacRegisters = IO(Flipped(new RegisterPort))
    val streams = IO(new ManagedGmacStreams)
    val runtimeAdmission = IO(new EthernetRuntimeAdmissionPort)
    val controlPark = IO(new EthernetRuntimeControlParkPort)
    val rawRgmiiRxRise = IO(Input(UInt(5.W)))
    val rawRgmiiRxFall = IO(Input(UInt(5.W)))
    val rgmiiTxRise = IO(Output(UInt(5.W)))
    val rgmiiTxFall = IO(Output(UInt(5.W)))
    val gmiiTxData = IO(Output(UInt(8.W)))
    val gmiiTxEnable = IO(Output(Bool()))
    val gmiiTxError = IO(Output(Bool()))
    val mdioIn = IO(Input(Bool()))
    val mdc = IO(Output(Bool()))
    val mdioOut = IO(Output(Bool()))
    val mdioOe = IO(Output(Bool()))
    val uartRx = IO(Input(Bool()))
    val uartTx = IO(Output(Bool()))
    val uartIrq = IO(Output(Bool()))
    val gmacIrq = IO(Output(Bool()))
    val cmuIrq = IO(Output(Bool()))
    val enabled = IO(Output(UInt(7.W)))
    val quiesce = IO(Output(UInt(7.W)))
    val isolate = IO(Output(UInt(7.W)))
    val linkUp = IO(Output(Bool()))
    val requestedSpeed = IO(Output(UInt(2.W)))
    val appliedSpeed = IO(Output(UInt(2.W)))
    val mediaPending = IO(Output(Bool()))

    val bank = Module(new ManagedRuntimeTestBank(config, slots))
    bank.sourceClock := sourceClock
    bank.alwaysOnClock := alwaysOnClock
    bank.rawUartClock := rawUartClock
    bank.rawTxClock.get := rawTxClock
    bank.rawRxClock.get := rawRxClock
    bank.commonReset := commonReset
    bank.cmuRegisters <> cmuRegisters
    bank.uartRegisters <> uartRegisters
    bank.gmacRegisters.get <> gmacRegisters
    bank.streams.get <> streams
    bank.runtimeAdmissionPort.get <> runtimeAdmission
    bank.controlPark.get <> controlPark
    bank.triSpeedRgmii.get.rxRise := rawRgmiiRxRise
    bank.triSpeedRgmii.get.rxFall := rawRgmiiRxFall
    rgmiiTxRise := bank.triSpeedRgmii.get.txRise
    rgmiiTxFall := bank.triSpeedRgmii.get.txFall
    linkUp := bank.triSpeedRgmii.get.linkUp
    requestedSpeed := bank.triSpeedRgmii.get.requestedSpeed
    appliedSpeed := bank.triSpeedRgmii.get.appliedSpeed
    mediaPending := bank.triSpeedRgmii.get.pending
    bank.gmiiRxData.get := 0.U
    bank.gmiiRxValid.get := false.B
    bank.gmiiRxError.get := false.B
    bank.linkUp.get := false.B // Unused legacy-GMII input, not the real PHY result.
    bank.mdioIn.get := mdioIn
    mdc := bank.mdc.get
    mdioOut := bank.mdioOut.get
    mdioOe := bank.mdioOe.get
    gmiiTxData := bank.gmiiTxData.get
    gmiiTxEnable := bank.gmiiTxEnable.get
    gmiiTxError := bank.gmiiTxError.get
    bank.uartRx := uartRx
    uartTx := bank.uartTx
    uartIrq := bank.uartIrq
    gmacIrq := bank.gmacIrq.get
    cmuIrq := bank.cmuIrq
    enabled := bank.enabled
    quiesce := bank.quiesce
    isolate := bank.isolate

    // Passive, named hierarchical taps for exact ownership/event scoreboards.
    // These keep existing real values; they do not fabricate completion or ACK.
    val mac = bank.instantiatedTriSpeedMac.get
    dontTouch(mac.frontend.io)
    dontTouch(mac.frontend.busy)
    dontTouch(mac.csr.io)
    dontTouch(mac.phy.io)
    dontTouch(mac.mdio.io)
    dontTouch(mac.mdioOwner.io)
    dontTouch(mac.dirty)
    dontTouch(mac.sentConfig)
    dontTouch(mac.txImage)
    dontTouch(mac.rxImage)
    dontTouch(mac.txConfig.source)
    dontTouch(mac.txConfig.destination)
    dontTouch(mac.txConfig.sourceIdle)
    dontTouch(mac.rxConfig.source)
    dontTouch(mac.rxConfig.destination)
    dontTouch(mac.rxConfig.sourceIdle)
    for (counters <- Seq(mac.txStats, mac.rxStats, mac.rxDiagnostics, mac.rawDiagnostics)) {
        dontTouch(counters.increment)
        dontTouch(counters.delta)
        dontTouch(counters.sourceIdle)
        dontTouch(counters.destinationIdle)
    }
    dontTouch(mac.rxStop.drained)
    dontTouch(mac.rxStop.settled)
    dontTouch(mac.rxStop.stopNewFrames)
    dontTouch(mac.tx.io)
    dontTouch(mac.rx.io)
    dontTouch(mac.physicalIngress.wholeFrameSkipped)
    dontTouch(mac.physicalIngress.overflow)
    dontTouch(mac.media.io)
}

object ManagedRuntimeControlMain extends App {
    val (positional, config) = NetworkDmaConfig.parseArgs(args)
    require(positional.length >= 1 && positional.length <= 2,
        "usage: ManagedRuntimeControlMain <rtl-dir> [tx-slots] [network options]")
    ChiselStage.emitSystemVerilogFile(
        new ManagedRuntimeControlFixture(config, positional.lift(1).map(_.toInt).getOrElse(2)),
        Array("--target-dir", positional(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization", "--preserve-values=named",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays", "--default-layer-specialization=enable"))
}
