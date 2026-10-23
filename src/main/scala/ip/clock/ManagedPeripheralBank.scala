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
    triSpeedEthernet: Boolean = false, triSpeedTxFrameSlots: Int = 1,
    val triSpeedRawClockHandoff: Boolean = false, balancedRawClocks: Boolean = false,
    sourceClockHz: Int = 0, rateDomains: Option[Seq[ClockRateParams]] = None,
    runtimeAdmission: Boolean = false, runtimeControlPark: Boolean = false,
    runtimeFixedMac: Boolean = false, runtimeRateControl: Boolean = false,
    performanceTelemetry: Boolean = false) extends RawModule {
    // CPU metadata and the actual MMIO/control source domain are independent.
    require(sourceClockHz >= 0)
    require(rateDomains.forall(_.size == 2))
    require(!performanceTelemetry || rateDomains.nonEmpty)
    require(!runtimeRateControl || (rateDomains.nonEmpty && runtimeFixedMac))
    private val busHz = if (sourceClockHz > 0) sourceClockHz else cpuHz
    require(!balancedRawClocks || (hardwareClocks && triSpeedEthernet))
    require(!(triSpeedRawClockHandoff && balancedRawClocks),
        "RAW MAC handoff with balanced raw clocks needs dedicated MAC lifecycle/CDC qualification")
    require(triSpeedTxFrameSlots == 1 || (triSpeedEthernet && triSpeedTxFrameSlots == 2))
    require(!triSpeedRawClockHandoff || triSpeedEthernet)
    require(!runtimeAdmission || triSpeedEthernet, "runtime network admission requires the tri-speed MAC")
    require(config.resources.size == 7 && config.gateableMask == 0x68)
    require(config.resources(1).nominalHz == cpuHz && config.resources(3).nominalHz == uartHz)
    require(!runtimeControlPark || triSpeedEthernet, "control park requires the tri-speed MAC")
    require(!runtimeFixedMac || (triSpeedEthernet && runtimeAdmission && runtimeControlPark &&
        !triSpeedRawClockHandoff), "fixed MAC requires the real runtime owners and continuous raw clock")
    val fixedMacRuntime = if (runtimeFixedMac) Some(IO(new FixedMacRuntimePort)) else None
    val controlPark = if (runtimeControlPark && !runtimeFixedMac) Some(IO(new EthernetRuntimeControlParkPort)) else None
    val sourceClock = IO(Input(Clock()))
    val alwaysOnClock = IO(Input(Clock()))
    val rawUartClock = IO(Input(Clock()))
    val rawTxClock = IO(Input(Clock()))
    val rawRxClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val cmuRegisters = IO(Flipped(new RegisterPort))
    val telemetryRegisters = if (performanceTelemetry) Some(IO(new RegisterPort)) else None
    val telemetrySourceIdle = if (performanceTelemetry) Some(IO(Input(Bool()))) else None
    val telemetryAonIdle = if (performanceTelemetry) Some(IO(Input(Bool()))) else None
    val uartRegisters = IO(Flipped(new RegisterPort))
    val gmacRegisters = IO(Flipped(new RegisterPort))
    val streams = IO(new ManagedGmacStreams)
    val runtimeAdmissionPort = if (runtimeAdmission && !runtimeFixedMac) Some(IO(new EthernetRuntimeAdmissionPort)) else None
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
    val rateEndpoints = rateDomains.map(_ => IO(Vec(2, new ClockRateEndpoint)))
    val rateStatus = rateDomains.map(_ => IO(Output(Vec(2, new ClockRateStatus))))
    val rateLeases = if (runtimeRateControl) Some(IO(Vec(2, new ClockRateDrainLease))) else None
    val rateBackendFault = if (runtimeRateControl) Some(IO(Input(UInt(2.W)))) else None
    val rateEmergencyStop = if (runtimeRateControl) Some(IO(Input(Bool()))) else None
    val rateSafety = if (runtimeRateControl) Some(IO(new FixedClockSafetyPort(16))) else None
    val runtimeFabricOwnerIdle = if (runtimeRateControl) Some(IO(Output(Bool()))) else None
    val runtimeAonControlIdle = if (runtimeRateControl) Some(IO(Output(Bool()))) else None
    val runtimeAonUartRunning = if (runtimeRateControl) Some(IO(Output(Bool()))) else None
    private val rateSourceIdle = if (runtimeRateControl) Some(Wire(Bool())) else None
    private val rateAonIdle = if (runtimeRateControl) Some(Wire(Bool())) else None
    val cmu = Module(new ClockManagementBoundary(config, runtimeObservation = runtimeRateControl))
    cmu.sourceClock := sourceClock
    cmu.alwaysOnClock := alwaysOnClock
    cmu.commonReset := commonReset
    rateDomains match {
        case None => cmu.registers <> cmuRegisters
        case Some(params) =>
            val release = Module(new CdcResetRelease)
            release.clockIn := sourceClock; release.asyncReset := commonReset
            val router = withClockAndReset(sourceClock, release.resetOut) {
                Module(new ClockRateRegisterRouter(config.base + 0x800, telemetry = performanceTelemetry))
            }
            val rateCmu = Module(new ClockRateManagementBoundary(params, config.base + 0x800,
                externalDrainLease = runtimeRateControl, backendFaultInput = runtimeRateControl))
            rateCmu.sourceClock := sourceClock; rateCmu.alwaysOnClock := alwaysOnClock
            rateCmu.commonReset := commonReset
            router.io.upstream <> cmuRegisters
            cmu.registers <> router.io.legacy
            rateCmu.registers <> router.io.rates
            telemetryRegisters.foreach(_ <> router.io.telemetryRegisters.get)
            rateEndpoints.get <> rateCmu.endpoints
            rateStatus.get := rateCmu.status
            rateLeases.foreach(_ <> rateCmu.leases.get)
            rateBackendFault.foreach(f => rateCmu.backendFault.get := f)
            rateSourceIdle.foreach(_ := router.io.idle && rateCmu.sourceIdle.get && telemetrySourceIdle.getOrElse(true.B))
            rateAonIdle.foreach(_ := rateCmu.aonIdle.get && telemetryAonIdle.getOrElse(true.B))
    }
    cmuIrq := cmu.irq
    for (n <- Seq(0, 1, 2, 4)) { cmu.resources(n).ack := false.B; cmu.resources(n).wake := false.B }
    val uart = Module(new ManagedUart(busHz, uartHz, config.alwaysOnHz, baud, hardwareClocks,
        balancedRawClock = balancedRawClocks, runtimeObservation = runtimeRateControl))
    uart.sourceClock := sourceClock
    uart.rawClock := rawUartClock
    uart.commonReset := commonReset
    uart.registers <> uartRegisters
    uart.control <> cmu.resources(3)
    uart.rx := uartRx
    uartTx := uart.tx
    uartIrq := uart.irq
    uartClock := uart.managedClock
    if (runtimeRateControl) {
        runtimeFabricOwnerIdle.get := cmu.sourceIdle.get && rateSourceIdle.get && uart.mmioIdle.get
        runtimeAonControlIdle.get := cmu.aonIdle.get && rateAonIdle.get
        // Do not confuse allowAdmission during a failed STOP retry with ON.
        // Once all accepted CMU owners close, only autonomous wake can modify
        // this STOP bit, and wake only clears it. Pre-gated UART cancels the
        // frequency request; runtime DFS never overwrites legacy user policy.
        val u = cmu.resources(3)
        runtimeAonUartRunning.get := !cmu.stopMask.get(3) && u.clockEnable &&
            u.allowAdmission && !u.quiesce && !u.isolate
    }
    // Scala-only constructed-instance witness; no RTL port, state or name change.
    private var builtTriSpeedMac: Option[TriSpeedManagedGmac] = None
    def instantiatedTriSpeedMac: Option[TriSpeedManagedGmac] = builtTriSpeedMac
    protected def buildTriSpeedMac(): TriSpeedManagedGmac =
        new TriSpeedManagedGmac(if (runtimeFixedMac) 125000000 else busHz, config.alwaysOnHz, hardwareClocks = hardwareClocks,
            networkDmaConfig = networkDmaConfig, txFrameSlots = triSpeedTxFrameSlots,
            rawClockHandoff = triSpeedRawClockHandoff, balancedRawClock = balancedRawClocks,
            runtimeAdmission = runtimeAdmission, runtimeControlPark = runtimeControlPark,
            exportContinuousClock = runtimeFixedMac)
    if (triSpeedEthernet) {
        val gmac = Module(buildTriSpeedMac())
        builtTriSpeedMac = Some(gmac)
        controlPark.foreach(_ <> gmac.controlPark.get)
        gmac.sourceClock := (if (runtimeFixedMac) gmac.continuousClock.get else sourceClock)
        gmac.rawTxClock := rawTxClock
        gmac.rawRxClock := rawRxClock
        gmac.commonReset := commonReset
        if (runtimeFixedMac) {
            val crossing = Module(new FixedMacBoundary(heldResponseStorage = true, deferredReleaseReceipt = true,
                emergencyAdmissionStop = runtimeRateControl))
            crossing.fabricClock := sourceClock
            crossing.fixedClock := gmac.continuousClock.get
            crossing.commonReset := commonReset
            if (runtimeRateControl) {
                crossing.emergencyStop.get := rateEmergencyStop.get
                val guard = Module(new FixedClockSafetyGuard(16))
                guard.aonClock := alwaysOnClock; guard.fixedClock := gmac.continuousClock.get
                guard.commonColdReset := commonReset
                guard.io <> rateSafety.get
                guard.safe := gmac.controlPark.get.parked &&
                    gmac.runtimeAdmissionPort.get.rxDrained && gmac.runtimeAdmissionPort.get.txDrained &&
                    crossing.fixedTxConsumersIdle && crossing.fixedRxStorageIdle && crossing.fixedCsrIdle.get
            }
            crossing.registers <> gmacRegisters
            crossing.macRegisters <> gmac.registers
            crossing.streams <> streams
            crossing.macStreams <> gmac.streams
            crossing.command <> fixedMacRuntime.get.command
            fixedMacRuntime.get.consumed <> crossing.consumed
            fixedMacRuntime.get.observation <> crossing.observation
            crossing.txProducersClosed := fixedMacRuntime.get.txProducersClosed
            crossing.controlProducersClosed := fixedMacRuntime.get.controlProducersClosed
            fixedMacRuntime.get.fabricCsrIdle := crossing.fabricCsrIdle
            fixedMacRuntime.get.fabricTxStorageIdle := crossing.fabricTxStorageIdle
            fixedMacRuntime.get.fabricRxConsumersIdle := crossing.fabricRxConsumersIdle
            crossing.admission <> gmac.runtimeAdmissionPort.get
            crossing.controlPark <> gmac.controlPark.get
            crossing.macIrq := gmac.irq
            gmacIrq := crossing.irq
        } else {
            gmac.registers <> gmacRegisters
            gmac.streams <> streams
            gmacIrq := gmac.irq
        }
        runtimeAdmissionPort.foreach { admission =>
            val macAdmission = gmac.runtimeAdmissionPort.get
            macAdmission.rxStopRequest := admission.rxStopRequest
            macAdmission.txStopRequest := admission.txStopRequest
            admission.rxDrained := macAdmission.rxDrained
            admission.txDrained := macAdmission.txDrained
            admission.released := macAdmission.released
        }
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
        txClock := gmac.txClock
        rxClock := gmac.rxClock
    } else {
        val gmac = Module(new ManagedGmac(busHz, config.alwaysOnHz, hardwareClocks = hardwareClocks,
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
