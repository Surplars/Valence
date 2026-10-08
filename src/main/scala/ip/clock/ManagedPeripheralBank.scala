package soc.ip.clock

import chisel3._
import soc.ip.bus._
import soc.ip.ethernet._
import soc.ip.uart.ManagedUart
import soc.ip.dma.NetworkDmaConfig

/** One CMU owner, protected CPU/time/DDR and three real managed endpoints.
  * CPU MMIO/control remains running; raw UART/RX capture and PHY clocks remain
  * running. No CPU implementation, DDR reset/DFS or RGMII I/O primitives here.
  */
class ManagedPeripheralBank(config: CmuParams, cpuHz: Int = 100000000,
    uartHz: Int = 50000000, baud: Int = 460800, hardwareClocks: Boolean = true,
    networkDmaConfig: NetworkDmaConfig = NetworkDmaConfig.Default,
    triSpeedEthernet: Boolean = false, triSpeedTxFrameSlots: Int = 1) extends RawModule {
    require(triSpeedTxFrameSlots == 1 || (triSpeedEthernet && triSpeedTxFrameSlots == 2))
    require(config.resources.size == 7 && config.gateableMask == 0x68)
    require(config.resources(1).nominalHz == cpuHz && config.resources(3).nominalHz == uartHz)
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
    val uartRx = IO(Input(Bool()))
    val uartTx = IO(Output(Bool()))
    val uartIrq = IO(Output(Bool()))
    val gmacIrq = IO(Output(Bool()))
    val cmuIrq = IO(Output(Bool()))
    val gmiiTxData = IO(Output(UInt(8.W)))
    val gmiiTxEnable = IO(Output(Bool()))
    val gmiiTxError = IO(Output(Bool()))
    val gmiiRxData = IO(Input(UInt(8.W)))
    val gmiiRxValid = IO(Input(Bool()))
    val gmiiRxError = IO(Input(Bool()))
    val linkUp = IO(Input(Bool()))
    val triSpeedRgmii = if (triSpeedEthernet) Some(IO(new TriSpeedRgmiiPortV1)) else None
    val mdc = IO(Output(Bool()))
    val mdioIn = IO(Input(Bool()))
    val mdioOut = IO(Output(Bool()))
    val mdioOe = IO(Output(Bool()))
    val uartClock = IO(Output(Clock()))
    val txClock = IO(Output(Clock()))
    val rxClock = IO(Output(Clock()))
    val enabled = IO(Output(UInt(7.W)))
    val quiesce = IO(Output(UInt(7.W)))
    val isolate = IO(Output(UInt(7.W)))
    val cmu = Module(new ClockManagementBoundary(config))
    cmu.sourceClock := sourceClock
    cmu.alwaysOnClock := alwaysOnClock
    cmu.commonReset := commonReset
    cmu.registers <> cmuRegisters
    cmuIrq := cmu.irq
    for (n <- Seq(0, 1, 2, 4)) { cmu.resources(n).ack := false.B; cmu.resources(n).wake := false.B }
    val uart = Module(new ManagedUart(cpuHz, uartHz, config.alwaysOnHz, baud, hardwareClocks))
    uart.sourceClock := sourceClock
    uart.rawClock := rawUartClock
    uart.commonReset := commonReset
    uart.registers <> uartRegisters
    uart.control <> cmu.resources(3)
    uart.rx := uartRx
    uartTx := uart.tx
    uartIrq := uart.irq
    uartClock := uart.managedClock
    if (triSpeedEthernet) {
        val gmac = Module(new TriSpeedManagedGmac(cpuHz, config.alwaysOnHz, hardwareClocks = hardwareClocks,
            networkDmaConfig = networkDmaConfig, txFrameSlots = triSpeedTxFrameSlots))
        gmac.sourceClock := sourceClock
        gmac.rawTxClock := rawTxClock
        gmac.rawRxClock := rawRxClock
        gmac.commonReset := commonReset
        gmac.registers <> gmacRegisters
        gmac.streams <> streams
        for (n <- 0 until 2) gmac.control(n) <> cmu.resources(n + 5)
        gmac.rawRgmiiRxRise := triSpeedRgmii.get.rxRise
        gmac.rawRgmiiRxFall := triSpeedRgmii.get.rxFall
        triSpeedRgmii.get.txRise := gmac.rgmiiTxRise
        triSpeedRgmii.get.txFall := gmac.rgmiiTxFall
        triSpeedRgmii.get.txClockRise := gmac.rgmiiTxClockRise
        triSpeedRgmii.get.txClockFall := gmac.rgmiiTxClockFall
        triSpeedRgmii.get.requestedSpeed := gmac.requestedSpeed
        triSpeedRgmii.get.appliedSpeed := gmac.appliedSpeed
        triSpeedRgmii.get.pending := gmac.mediaPending
        triSpeedRgmii.get.linkUp := gmac.linkUp
        triSpeedRgmii.get.txIdle := gmac.txIdle
        triSpeedRgmii.get.rxDrained := gmac.rxDrained
        gmac.mdioIn := mdioIn
        gmiiTxData := gmac.gmiiTxData
        gmiiTxEnable := gmac.gmiiTxEnable
        gmiiTxError := gmac.gmiiTxError
        mdc := gmac.mdc
        mdioOut := gmac.mdioOut
        mdioOe := gmac.mdioOe
        gmacIrq := gmac.irq
        txClock := gmac.txClock
        rxClock := gmac.rxClock
    } else {
        val gmac = Module(new ManagedGmac(cpuHz, config.alwaysOnHz, hardwareClocks = hardwareClocks,
            networkDmaConfig = networkDmaConfig))
        gmac.sourceClock := sourceClock
        gmac.rawTxClock := rawTxClock
        gmac.rawRxClock := rawRxClock
        gmac.commonReset := commonReset
        gmac.registers <> gmacRegisters
        gmac.streams <> streams
        for (n <- 0 until 2) gmac.control(n) <> cmu.resources(n + 5)
        gmac.gmiiRxData := gmiiRxData
        gmac.gmiiRxValid := gmiiRxValid
        gmac.gmiiRxError := gmiiRxError
        gmac.linkUp := linkUp
        gmac.mdioIn := mdioIn
        gmiiTxData := gmac.gmiiTxData
        gmiiTxEnable := gmac.gmiiTxEnable
        gmiiTxError := gmac.gmiiTxError
        mdc := gmac.mdc
        mdioOut := gmac.mdioOut
        mdioOe := gmac.mdioOe
        gmacIrq := gmac.irq
        txClock := gmac.txClock
        rxClock := gmac.rxClock
    }
    enabled := VecInit(cmu.resources.map(_.clockEnable)).asUInt
    quiesce := VecInit(cmu.resources.map(_.quiesce)).asUInt
    isolate := VecInit(cmu.resources.map(_.isolate)).asUInt
}
