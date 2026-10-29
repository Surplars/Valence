package platform

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.bus._
import soc.ip.ethernet._
import soc.ip.dma.NetworkDmaConfig
import soc.platform._

/** Boundary/adapter unit fixture. MAC-side ownership and upstream closure are
  * explicit test inputs, NOT whole-platform evidence or substitute acknowledgements.
  */
class CommonFixedMacAdapterFixture extends RawModule {
    val fabricClock = IO(Input(Clock()))
    val fixedClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val owner = IO(Input(Valid(UInt(8.W))))
    val rxStop = IO(Input(Bool()))
    val txStop = IO(Input(Bool()))
    val park = IO(Input(Bool()))
    val txClosed = IO(Input(Bool()))
    val rawHeld = IO(Input(Bool()))
    val terminalConsumed = IO(Input(Bool()))
    val retired = IO(Input(Bool()))
    val holdFinalSnapshot = IO(Input(Bool()))
    val registers = IO(Flipped(new RegisterPort))
    val macRegisters = IO(new RegisterPort)
    val streams = IO(new ManagedGmacStreams)
    val macStreams = IO(Flipped(new ManagedGmacStreams))
    val admission = IO(Flipped(new EthernetRuntimeAdmissionPort))
    val controlPark = IO(Flipped(new EthernetRuntimeControlParkPort))
    val macIrq = IO(Input(Bool()))
    val irq = IO(Output(Bool()))
    val txDrained = IO(Output(Bool()))
    val rxDrained = IO(Output(Bool()))
    val parked = IO(Output(Bool()))
    val released = IO(Output(Bool()))
    val fault = IO(Output(Bool()))
    val commandFire = IO(Output(Bool()))
    val commandBits = IO(Output(new FixedMacCommand))
    val receiptFire = IO(Output(Bool()))
    val receiptBits = IO(Output(new FixedMacCommand))
    val snapshotBlocked = IO(Output(Bool()))
    val snapshotFire = IO(Output(Bool()))
    val snapshotBits = IO(Output(new FixedMacObservation))
    val release = Module(new CdcResetRelease)
    release.clockIn := fabricClock; release.asyncReset := commonReset
    val p = CommonCpuTilePortParams(runtimeMaintenance = true, runtimeCancellation = true,
        runtimeInterruptHold = true)
    val adapter = withClockAndReset(fabricClock, release.resetOut) {
        Module(new CommonFixedMacRuntimeAdapter(p))
    }
    val crossing = Module(new FixedMacBoundary(heldResponseStorage = true, deferredReleaseReceipt = true))
    crossing.fabricClock := fabricClock; crossing.fixedClock := fixedClock; crossing.commonReset := commonReset
    crossing.registers <> registers; macRegisters <> crossing.macRegisters
    crossing.streams <> streams; macStreams <> crossing.macStreams
    admission <> crossing.admission; controlPark <> crossing.controlPark
    crossing.macIrq := macIrq; irq := crossing.irq
    adapter.io.owner := owner; adapter.io.rxStop := rxStop; adapter.io.txStop := txStop; adapter.io.park := park
    adapter.io.txProducersClosed := txClosed
    // Emulate the raw-held dependency on network admission, exercising the PARK
    // causality without claiming the explicit input is a real fabric owner.
    adapter.io.controlProducersClosed := rawHeld && adapter.io.txDrained && adapter.io.rxDrained &&
        !registers.request.valid
    adapter.io.terminalConsumedAtAon := terminalConsumed; adapter.io.retired := retired
    adapter.io.boundary.command <> crossing.command
    adapter.io.boundary.consumed <> crossing.consumed
    adapter.io.boundary.observation <> crossing.observation
    val block = holdFinalSnapshot && crossing.observation.bits.released
    adapter.io.boundary.observation.valid := crossing.observation.valid && !block
    crossing.observation.ready := adapter.io.boundary.observation.ready && !block
    crossing.txProducersClosed := adapter.io.boundary.txProducersClosed
    crossing.controlProducersClosed := adapter.io.boundary.controlProducersClosed
    adapter.io.boundary.fabricCsrIdle := crossing.fabricCsrIdle
    adapter.io.boundary.fabricTxStorageIdle := crossing.fabricTxStorageIdle
    adapter.io.boundary.fabricRxConsumersIdle := crossing.fabricRxConsumersIdle
    txDrained := adapter.io.txDrained; rxDrained := adapter.io.rxDrained
    parked := adapter.io.parked; released := adapter.io.released; fault := adapter.io.fault
    commandFire := crossing.command.fire; commandBits := crossing.command.bits
    receiptFire := crossing.consumed.fire; receiptBits := crossing.consumed.bits
    snapshotBlocked := crossing.observation.valid && block
    snapshotFire := crossing.observation.fire; snapshotBits := crossing.observation.bits
}

object CommonFixedMacAdapterMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new CommonFixedMacAdapterFixture, Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization", "--preserve-values=named",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
object CommonRuntimeFixedMacPlatformMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new CommonMachinePlatform(CommonCpuProfile.I1Performance300,
        programmable = true, hardwareClocks = false, vivadoMemories = false,
        independentDdrClock = true, independentTimebaseClock = true, independentDebugClock = true,
        runtimeDebugAdmission = true, runtimeNetworkAdmission = true, runtimeFixedQualification = true,
        runtimeControlQualification = true, runtimeFixedMac = true), Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}

/** Real r20 I1/Home/DMA/DDR/timer owners with the r23 production bank option.
  * Fixed source is ALWAYS the same continuous 125 MHz leaf. There is no fixture
  * source-clock rejoin/mux. Only PHY policy WAIT intervals are shortened.
  */
class FixedMacEpochTestMac(config: NetworkDmaConfig)
    extends TriSpeedManagedGmac(cpuHz = 125000000, hardwareClocks = false,
        networkDmaConfig = config, txFrameSlots = 2, runtimeAdmission = true,
        runtimeControlPark = true, exportContinuousClock = true) {
    override def desiredName: String = "TriSpeedManagedGmac"
    override protected def buildPhyManager(): Rtl8211fPhyManager =
        new Rtl8211fPhyManager(125000000, startupCycles = 256, pollCycles = 512, runtimePark = true)
    val observe = IO(new ManagedEpochPacketObservations)
    txConfig.destination.ready := !tx.io.busy && !observe.holdConfigConsume
    rxConfig.destination.ready := rxConfigurationIdle && !observe.holdConfigConsume
    observe.configImageBlocked := observe.holdConfigConsume &&
        (txConfig.destination.valid || rxConfig.destination.valid)
    observe.rxAdmissionClosed := rxStop.stopNewFrames
    observe.rxAccepted := rx.io.accepted
    observe.rxDropped := rx.io.dropped
    observe.rxDropReasons := rx.io.dropReasons.get
    observe.rxBadFcs := rx.io.badFcs
    observe.txBusy := tx.io.busy
    observe.txDone := tx.io.done
    observe.rxDestinationIdle := rxFifo.destinationIdle
    observe.txSourceIdle := txFifo.sourceIdle
    observe.sourceResetReleased := !cpuRelease.resetOut.asBool && !rawTxRelease.resetOut.asBool &&
        !rawRxRelease.resetOut.asBool && !txRelease.resetOut.asBool && !rxRelease.resetOut.asBool
    observe.packetOwnersIdle := adapter.io.txIdle && adapter.io.rxIdle &&
        txFifo.sourceIdle && txFifo.destinationIdle && rxFifo.sourceIdle && rxFifo.destinationIdle &&
        !tx.io.busy && !rx.io.ownedBusy.get
    dontTouch(frontend.io)
    dontTouch(csr.io)
    dontTouch(phy.io)
    dontTouch(mdio.io)
    dontTouch(mdioOwner.io)
    dontTouch(txConfig.source)
    dontTouch(txConfig.destination)
    dontTouch(rxConfig.source)
    dontTouch(rxConfig.destination)
    dontTouch(sentConfig)
    dontTouch(txImage)
    dontTouch(rxImage)
}

class FixedMacEpochTestBank(config: NetworkDmaConfig)
    extends soc.ip.clock.ManagedPeripheralBank(ip.ManagedPeripheralTestConfig.params.copy(timeoutCycles = 65536),
        hardwareClocks = false, networkDmaConfig = config, triSpeedEthernet = true,
        triSpeedTxFrameSlots = 2, runtimeAdmission = true, runtimeControlPark = true, runtimeFixedMac = true) {
    override def desiredName: String = "ManagedPeripheralBank"
    val localPark = IO(Output(new EthernetRuntimeControlParkPort))
    localPark := instantiatedTriSpeedMac.get.controlPark.get
    val localAdmission = IO(Output(new EthernetRuntimeAdmissionPort))
    localAdmission := instantiatedTriSpeedMac.get.runtimeAdmissionPort.get
    override protected def buildTriSpeedMac(): TriSpeedManagedGmac = new FixedMacEpochTestMac(config)
    val observe = IO(new ManagedEpochPacketObservations)
    observe <> instantiatedTriSpeedMac.get.asInstanceOf[FixedMacEpochTestMac].observe
}

class CommonFixedMacEpochFixture extends CommonI1RuntimeFixedFixture {
    override def makeRuntime(): CommonRuntimeEpochBoundary = new CommonRuntimeEpochBoundary(boundary,
        drainTimeoutCycles = 65536, cleanupTimeoutCycles = 65536, externalRetirementBarrier = true)
    // Lazy construction is required because the inherited elaboration hooks run
    // while their owning base class is being built. No inherited packet owner is
    // instantiated on this branch, and no superclass assertion is overwritten.
    lazy val controlRegisters = IO(Flipped(new RegisterPort))
    lazy val fixedMacControl = IO(new Bundle {
        val holdFinalSnapshot = Input(Bool())
        val snapshotBlocked = Output(Bool())
        val snapshotFire = Output(Bool())
        val snapshotReleased = Output(Bool())
        val commandFire = Output(Bool())
        val command = Output(new FixedMacCommand)
        val receiptFire = Output(Bool())
        val receipt = Output(new FixedMacCommand)
        val fabricCsrIdle = Output(Bool())
        val fabricRxIdle = Output(Bool())
        val fault = Output(Bool())
    })
    lazy val fixedAdapter = withClockAndReset(fabricClock, fabricRelease.resetOut) {
        Module(new CommonFixedMacRuntimeAdapter(boundary))
    }
    lazy val managed = IO(new Bundle {
        val holdConfigConsume = Input(Bool())
        val mdioIn = Input(Bool())
        val mdc = Output(Bool())
        val mdioOut = Output(Bool())
        val mdioOe = Output(Bool())
        val linkUp = Output(Bool())
        val appliedSpeed = Output(UInt(2.W))
        val mediaPending = Output(Bool())
        val configImageBlocked = Output(Bool())
        val parkRequest = Output(Bool())
        val parked = Output(Bool())
        val released = Output(Bool())
        val csrDrained = Output(Bool())
        val configDrained = Output(Bool())
        val mdioDrained = Output(Bool())
        val phyParked = Output(Bool())
        val phyFault = Output(UInt(4.W))
        val statisticsPending = Output(UInt(4.W))
        val qualified = Output(Valid(UInt(boundary.maintenanceEpochBits.W)))
        val retirementPermit = Output(Bool())
        val busy = Output(Bool())
        val fault = Output(Bool())
    })
    lazy val bank = Module(new FixedMacEpochTestBank(fabric.fpga.network))

    override protected def wireMacRegisters(): Unit = {
        bank.sourceClock := fabricClock
        bank.alwaysOnClock := alwaysOnClock
        bank.rawUartClock := alwaysOnClock
        bank.rawTxClock.get := txClock
        bank.rawRxClock.get := rxClock
        bank.commonReset := commonColdReset
        for (port <- Seq(bank.cmuRegisters, bank.uartRegisters)) {
            port.request.valid := false.B
            port.request.bits := 0.U.asTypeOf(port.request.bits)
            port.response.ready := true.B
        }
        bank.uartRx := true.B
        bank.gmiiRxData.get := 0.U
        bank.gmiiRxValid.get := false.B
        bank.gmiiRxError.get := false.B
        bank.linkUp.get := false.B // Unused legacy GMII input, not the real PHY.
        bank.mdioIn.get := managed.mdioIn
        managed.mdc := bank.mdc.get
        managed.mdioOut := bank.mdioOut.get
        managed.mdioOe := bank.mdioOe.get
        bank.triSpeedRgmii.get.rxRise := Cat(packet.gmiiRxValid, packet.gmiiRxData(3, 0))
        bank.triSpeedRgmii.get.rxFall := Cat(packet.gmiiRxValid ^ packet.gmiiRxError, packet.gmiiRxData(7, 4))
        managed.linkUp := bank.triSpeedRgmii.get.linkUp
        managed.appliedSpeed := bank.triSpeedRgmii.get.appliedSpeed
        managed.mediaPending := bank.triSpeedRgmii.get.pending
        bank.observe.holdConfigConsume := managed.holdConfigConsume
        managed.configImageBlocked := bank.observe.configImageBlocked
        // This independent test master owns real CSR requests and can hold a
        // genuine accepted reply. CPU's real decoded CSR route remains intact.
        val controlArbiter = withClockAndReset(fabricClock, fabricRelease.resetOut) {
            Module(new TwoMasterRegisterArbiter(lockRequests = true, resetRoundRobin = true))
        }
        controlArbiter.io.masters(0) <> fabric.io.ethernetRegisters.get
        controlArbiter.io.masters(1) <> controlRegisters
        bank.gmacRegisters.get <> controlArbiter.io.downstream
    }

    override protected def wirePacketPlane(): Unit = {
        val streams = fabric.io.ethernetStreams.get
        val endpoint = bank.streams.get
        streams.rxData <> endpoint.rxData
        streams.rxStatus <> endpoint.rxStatus
        val statusAllow = !packet.holdRxStatusLast || !endpoint.rxStatus.bits.last
        streams.rxStatus.valid := endpoint.rxStatus.valid && statusAllow
        endpoint.rxStatus.ready := streams.rxStatus.ready && statusAllow
        endpoint.txData <> streams.txData
        endpoint.txControl <> streams.txControl
        val controlAllow = !packet.holdTxControlLast || !streams.txControl.bits.last
        endpoint.txControl.valid := streams.txControl.valid && controlAllow
        streams.txControl.ready := endpoint.txControl.ready && controlAllow
        val dataAllow = !packet.holdTxDataLast || !streams.txData.bits.last
        endpoint.txData.valid := streams.txData.valid && dataAllow
        streams.txData.ready := endpoint.txData.ready && dataAllow
        val a = fixedAdapter
        val port = bank.fixedMacRuntime.get
        a.io.boundary <> port
        val block = fixedMacControl.holdFinalSnapshot && port.observation.bits.released
        a.io.boundary.observation.valid := port.observation.valid && !block
        port.observation.ready := a.io.boundary.observation.ready && !block
        a.io.owner.valid := network.io.busy
        a.io.owner.bits := network.io.held.bits
        a.io.rxStop := network.io.rxStop
        a.io.txStop := network.io.txStop
        a.io.txProducersClosed := network.io.dmaPause && fabric.io.networkTxIdle.get &&
            !streams.txData.valid && !streams.txControl.valid
        // Includes the test CSR arbiter's genuine upstream offer, not merely
        // the CPU-side register port that could be temporarily unselected.
        a.io.controlProducersClosed := fabric.io.runtimeHeld.get.valid &&
            fabric.io.runtimeHeld.get.bits === network.io.held.bits && fabric.io.allObligationsIdle &&
            !bank.gmacRegisters.get.request.valid && !controlRegisters.request.valid
        a.io.terminalConsumedAtAon := runtime.io.terminalConsumedAtAon.get
        a.io.retired := runtime.io.runtimeComplete.fire
        network.io.macRxDrained := a.io.rxDrained
        network.io.macTxDrained := a.io.txDrained
        network.io.macReleased := a.io.released
        network.io.fault := sequencer.fault || a.io.fault
        packet.rxDrained := a.io.rxDrained
        packet.txDrained := a.io.txDrained
        packet.released := Mux(a.io.busy, a.io.released, bank.localAdmission.released)
        fixedMacControl.snapshotBlocked := port.observation.valid && block
        fixedMacControl.snapshotFire := port.observation.fire
        fixedMacControl.snapshotReleased := port.observation.bits.released
        fixedMacControl.commandFire := port.command.fire
        fixedMacControl.command := port.command.bits
        fixedMacControl.receiptFire := port.consumed.fire
        fixedMacControl.receipt := port.consumed.bits
        fixedMacControl.fabricCsrIdle := port.fabricCsrIdle
        fixedMacControl.fabricRxIdle := port.fabricRxConsumersIdle
        fixedMacControl.fault := a.io.fault
        packet.rxAdmissionClosed := bank.observe.rxAdmissionClosed
        packet.rxAccepted := bank.observe.rxAccepted
        packet.rxDropped := bank.observe.rxDropped
        packet.rxDropReasons := bank.observe.rxDropReasons
        packet.rxBadFcs := bank.observe.rxBadFcs
        packet.txBusy := bank.observe.txBusy
        packet.txDone := bank.observe.txDone
        packet.gmiiTxData := bank.gmiiTxData.get
        packet.gmiiTxEnable := bank.gmiiTxEnable.get
        packet.gmiiTxError := bank.gmiiTxError.get
        packet.rxStatusLastBlocked := endpoint.rxStatus.valid && endpoint.rxStatus.bits.last && !statusAllow
        packet.txControlLastBlocked := streams.txControl.valid && streams.txControl.bits.last && !controlAllow
        packet.txDataLastBlocked := streams.txData.valid && streams.txData.bits.last && !dataAllow
        packet.rxDataFire := streams.rxData.fire
        packet.rxDataLastFire := streams.rxData.fire && streams.rxData.bits.last
        packet.rxStatusFire := streams.rxStatus.fire
        packet.rxStatusData := streams.rxStatus.bits.data
        packet.rxStatusLastFire := streams.rxStatus.fire && streams.rxStatus.bits.last
        packet.txControlFire := streams.txControl.fire
        packet.txDataFire := streams.txData.fire
        packet.txDataLastFire := streams.txData.fire && streams.txData.bits.last
        packet.rxDestinationIdle := bank.fixedMacRuntime.get.fabricRxConsumersIdle
        packet.txSourceIdle := bank.fixedMacRuntime.get.fabricTxStorageIdle
    }

    val controlEpoch = withClockAndReset(fabricClock, fabricRelease.resetOut) {
        Module(new CommonControlParkEpochSequencer(boundary))
    }
    controlEpoch.io.prepare.valid := fabric.io.externalMaintenance.fire
    controlEpoch.io.prepare.bits := fabric.io.externalMaintenance.bits.epoch
    controlEpoch.io.fabricHeld := fabric.io.runtimeHeld.get
    controlEpoch.io.fabricAllObligationsIdle := fabric.io.allObligationsIdle
    controlEpoch.io.completion.valid := runtime.io.runtimeComplete.valid
    controlEpoch.io.completion.bits := runtime.io.runtimeComplete.bits
    controlEpoch.io.terminalConsumedAtAon := runtime.io.terminalConsumedAtAon.get
    controlEpoch.io.retired := runtime.io.runtimeComplete.fire
    val park = bank.localPark
    fixedAdapter.io.park := controlEpoch.io.parkRequest
    controlEpoch.io.parked := fixedAdapter.io.parked
    controlEpoch.io.parkReleased := fixedAdapter.io.released
    managed.parkRequest := controlEpoch.io.parkRequest
    managed.parked := fixedAdapter.io.parked
    // Before/after an epoch this diagnostic exposes real source release only;
    // runtime retirement always uses the tagged delayed adapter receipt above.
    managed.released := Mux(fixedAdapter.io.busy, fixedAdapter.io.released, park.released)
    managed.csrDrained := park.csrDrained && bank.fixedMacRuntime.get.fabricCsrIdle
    managed.configDrained := park.configDrained
    managed.mdioDrained := park.mdioDrained
    managed.phyParked := park.phyParked
    managed.phyFault := park.phyFault
    managed.statisticsPending := park.statisticsPending
    managed.qualified := controlEpoch.io.qualified
    managed.retirementPermit := controlEpoch.io.retirementPermit
    managed.busy := controlEpoch.io.busy
    managed.fault := controlEpoch.io.fault
    val controlMatches = controlEpoch.io.qualified.valid &&
        controlEpoch.io.qualified.bits === fabric.io.runtimeHeld.get.bits
    // Extend the genuine r19 observation/retirement joins, not its drain path.
    runtime.io.fabricHeld.valid := fabric.io.runtimeHeld.get.valid && fixedDdrFabricIdle &&
        fixedTimerFabricIdle && ddrMatches && timerMatches && controlMatches
    runtime.io.retirementPermit.get := sequencer.retirementPermit && network.io.retirementPermit &&
        ddrQualifier.retirementPermit && timerQualifier.retirementPermit && controlEpoch.io.retirementPermit
    runtime.io.retirementFault.get := sequencer.fault || fixed.fault || controlEpoch.io.fault || fixedAdapter.io.fault
}

object CommonFixedMacEpochNativeMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new CommonFixedMacEpochFixture, Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization", "--preserve-values=named",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
