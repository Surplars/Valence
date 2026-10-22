package platform

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import ip.{ManagedRuntimeTestBank, ManagedRuntimeTestMac}
import soc.ip.bus.{RegisterPort, TwoMasterRegisterArbiter}
import soc.ip.dma.NetworkDmaConfig
import soc.ip.ethernet._
import soc.platform._

/** Passive packet observations plus a test-only backpressure gate at real
  * configuration image consumption. The held mailbox owns its original image;
  * no request, reply, PHY result or epoch acknowledgement is manufactured.
  */
class ManagedEpochPacketObservations extends Bundle {
    val holdConfigConsume = Input(Bool())
    val configImageBlocked = Output(Bool())
    val rxAdmissionClosed = Output(Bool())
    val rxAccepted = Output(Bool())
    val rxDropped = Output(Bool())
    val rxDropReasons = Output(UInt(8.W))
    val rxBadFcs = Output(Bool())
    val txBusy = Output(Bool())
    val txDone = Output(Bool())
    val rxDestinationIdle = Output(Bool())
    val txSourceIdle = Output(Bool())
    val sourceResetReleased = Output(Bool())
    val packetOwnersIdle = Output(Bool())
}

class ManagedEpochTestMac(config: NetworkDmaConfig)
    extends ManagedRuntimeTestMac(config, slots = 2) {
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

class ManagedEpochTestBank(config: NetworkDmaConfig)
    extends ManagedRuntimeTestBank(config, slots = 2) {
    override protected def buildTriSpeedMac(): TriSpeedManagedGmac = new ManagedEpochTestMac(config)
    val observe = IO(new ManagedEpochPacketObservations)
    observe <> instantiatedTriSpeedMac.get.asInstanceOf[ManagedEpochTestMac].observe
}

/** Real r19 I1/private caches/Home/DDR/timer/debug integration, replacing the
  * omitted-control/simple-MAC plane with ONE actual managed peripheral bank.
  * Eight unrelated runtime clocks stay running apart from explicit adversarial
  * fixed-clock stalls. An optional preboot-only source clock separates real PHY
  * initialization while all bus owners are empty, then rejoins fabric edges. The PHY pins and external AXI endpoint are models.
  * Only r18 policy WAIT intervals are shortened: startup=256, poll=512. Actual
  * MDIO divider/transactions and PHY page/debounce/recovery logic are unchanged.
  * This is an opt-in control epoch join, never a four-class clock gate ACK.
  */
class CommonManagedControlEpochFixture extends CommonI1RuntimeFixedFixture {
    override def makeRuntime(): CommonRuntimeEpochBoundary = new CommonRuntimeEpochBoundary(boundary,
        drainTimeoutCycles = 65536, cleanupTimeoutCycles = 65536, externalRetirementBarrier = true)
    // Lazy construction is required because the inherited elaboration hooks run
    // while their owning base class is being built. No inherited packet owner is
    // instantiated on this branch, and no superclass assertion is overwritten.
    lazy val controlRegisters = IO(Flipped(new RegisterPort))
    // Test-only preboot scheduling. The bench supplies the actual source clock;
    // no clock mux, frequency transition, epoch proof or default changes exist
    // in production. A real local park drains both handover boundaries.
    lazy val bootstrap = IO(new Bundle {
        val sourceClock = Input(Clock())
        val park = Input(Bool())
        val resetReleased = Output(Bool())
        val boundaryEmpty = Output(Bool())
    })
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
    lazy val bank = Module(new ManagedEpochTestBank(fabric.fpga.network))

    override protected def wireMacRegisters(): Unit = {
        bank.sourceClock := bootstrap.sourceClock
        bank.alwaysOnClock := alwaysOnClock
        bank.rawUartClock := alwaysOnClock
        bank.rawTxClock := txClock
        bank.rawRxClock := rxClock
        bank.commonReset := commonColdReset
        for (port <- Seq(bank.cmuRegisters, bank.uartRegisters)) {
            port.request.valid := false.B
            port.request.bits := 0.U.asTypeOf(port.request.bits)
            port.response.ready := true.B
        }
        bank.uartRx := true.B
        bank.gmiiRxData := 0.U
        bank.gmiiRxValid := false.B
        bank.gmiiRxError := false.B
        bank.linkUp := false.B // Unused legacy GMII input, not the real PHY.
        bank.mdioIn := managed.mdioIn
        managed.mdc := bank.mdc
        managed.mdioOut := bank.mdioOut
        managed.mdioOe := bank.mdioOe
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
        bank.gmacRegisters <> controlArbiter.io.downstream
    }

    override protected def wirePacketPlane(): Unit = {
        val streams = fabric.io.ethernetStreams.get
        val endpoint = bank.streams
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
        val admission = bank.runtimeAdmissionPort.get
        admission.rxStopRequest := network.io.rxStop
        admission.txStopRequest := network.io.txStop
        network.io.macRxDrained := admission.rxDrained
        network.io.macTxDrained := admission.txDrained
        network.io.macReleased := admission.released
        packet.rxDrained := admission.rxDrained
        packet.txDrained := admission.txDrained
        packet.released := admission.released
        packet.rxAdmissionClosed := bank.observe.rxAdmissionClosed
        packet.rxAccepted := bank.observe.rxAccepted
        packet.rxDropped := bank.observe.rxDropped
        packet.rxDropReasons := bank.observe.rxDropReasons
        packet.rxBadFcs := bank.observe.rxBadFcs
        packet.txBusy := bank.observe.txBusy
        packet.txDone := bank.observe.txDone
        packet.gmiiTxData := bank.gmiiTxData
        packet.gmiiTxEnable := bank.gmiiTxEnable
        packet.gmiiTxError := bank.gmiiTxError
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
        packet.rxDestinationIdle := bank.observe.rxDestinationIdle
        packet.txSourceIdle := bank.observe.txSourceIdle
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
    val park = bank.controlPark.get
    park.request := controlEpoch.io.parkRequest || bootstrap.park
    controlEpoch.io.parked := park.parked
    controlEpoch.io.parkReleased := park.released
    managed.parkRequest := park.request
    managed.parked := park.parked
    managed.released := park.released
    managed.csrDrained := park.csrDrained
    managed.configDrained := park.configDrained
    managed.mdioDrained := park.mdioDrained
    managed.phyParked := park.phyParked
    managed.phyFault := park.phyFault
    managed.statisticsPending := park.statisticsPending
    managed.qualified := controlEpoch.io.qualified
    managed.retirementPermit := controlEpoch.io.retirementPermit
    managed.busy := controlEpoch.io.busy
    managed.fault := controlEpoch.io.fault
    bootstrap.resetReleased := bank.observe.sourceResetReleased &&
        !fabricRelease.resetOut.asBool && !cpuRelease.resetOut.asBool
    val bootstrapStreams = fabric.io.ethernetStreams.get
    bootstrap.boundaryEmpty := !fabric.io.ethernetRegisters.get.request.valid &&
        !fabric.io.ethernetRegisters.get.response.valid && !controlRegisters.request.valid &&
        !controlRegisters.response.valid && !bank.gmacRegisters.request.valid &&
        !bank.gmacRegisters.response.valid && !bootstrapStreams.rxData.valid &&
        !bootstrapStreams.rxStatus.valid && !bootstrapStreams.txData.valid &&
        !bootstrapStreams.txControl.valid && bank.observe.packetOwnersIdle
    withClockAndReset(bootstrap.sourceClock, commonColdReset) {
        when(bootstrap.park) {
            assert(!io.start && !controlEpoch.io.busy && !fabric.io.externalMaintenance.valid,
                "test bootstrap park overlapped CPU or runtime epoch")
        }
    }
    val controlMatches = controlEpoch.io.qualified.valid &&
        controlEpoch.io.qualified.bits === fabric.io.runtimeHeld.get.bits
    // Extend the genuine r19 observation/retirement joins, not its drain path.
    runtime.io.fabricHeld.valid := fabric.io.runtimeHeld.get.valid && fixedDdrFabricIdle &&
        fixedTimerFabricIdle && ddrMatches && timerMatches && controlMatches
    runtime.io.retirementPermit.get := sequencer.retirementPermit && network.io.retirementPermit &&
        ddrQualifier.retirementPermit && timerQualifier.retirementPermit && controlEpoch.io.retirementPermit
    runtime.io.retirementFault.get := sequencer.fault || fixed.fault || controlEpoch.io.fault
}

object CommonManagedControlEpochNativeMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new CommonManagedControlEpochFixture, Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization", "--preserve-values=named",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}

object CommonRuntimeControlPlatformMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new CommonMachinePlatform(CommonCpuProfile.I1Performance300,
        programmable = true, hardwareClocks = false, vivadoMemories = false,
        independentDdrClock = true, independentTimebaseClock = true, independentDebugClock = true,
        runtimeDebugAdmission = true, runtimeNetworkAdmission = true, runtimeFixedQualification = true,
        runtimeControlQualification = true), Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
