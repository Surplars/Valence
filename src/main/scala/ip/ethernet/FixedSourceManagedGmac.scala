package soc.ip.ethernet

import chisel3._
import chisel3.util._
import soc.ip.bus._
import soc.ip.clock.ClockResourceControl
import soc.ip.dma.{EthernetAxisWord, NetworkDmaConfig}

/** Full-state votes, not a fabricated CPU/DMA idle or clock-gate acknowledgement.
  * serial is strictly increasing until common cold reset; epoch is the caller's
  * transaction identity. Several ordered commands may belong to one epoch.
  */
class FixedMacCommand extends Bundle {
    val epoch = UInt(16.W)
    val serial = UInt(16.W)
    val rxStop = Bool()
    val txStop = Bool()
    val park = Bool()
}

/** Coherent, delayed fixed-domain observation. Both true and false states cross.
  * RX includes source storage but NOT fabric output/DMA consumers. CSR includes
  * destination ownership but NOT the final fabric reply. Never use alone to gate.
  */
class FixedMacObservation extends Bundle {
    val command = new FixedMacCommand
    val txDrained = Bool()
    val rxDrained = Bool()
    val released = Bool()
    val parked = Bool()
    val csrDrained = Bool()
    val configDrained = Bool()
    val mdioDrained = Bool()
    val phyParked = Bool()
    val mediaSettled = Bool()
    val phyFault = UInt(4.W)
    val statisticsPending = UInt(4.W)
}

/** Fabric-facing control of the fixed MAC boundary. The bank owns no epoch. */
class FixedMacRuntimePort extends Bundle {
    val command = Flipped(Decoupled(new FixedMacCommand))
    val consumed = Decoupled(new FixedMacCommand)
    val observation = Decoupled(new FixedMacObservation)
    val txProducersClosed = Input(Bool())
    val controlProducersClosed = Input(Bool())
    val fabricCsrIdle = Output(Bool())
    val fabricTxStorageIdle = Output(Bool())
    val fabricRxConsumersIdle = Output(Bool())
}

/** Reusable, opt-in transport around the complete fixed-clock MAC source island.
  * There is deliberately no platform runtime endpoint or epoch allocator here.
  *
  * Before offering txStop, caller closes/completes upstream TX producers. Before
  * offering park it must additionally own the real matching fabric-held proof
  * and close/complete upstream CSR producers. The two explicit witness inputs
  * are integration obligations, not internally manufactured owner proofs.
  *
  * TX command launch waits BOTH source pointer-empty predicates. Thus every old
  * word has already reached a destination output before the command can cross.
  * Fixed TX stop additionally waits BOTH destination predicates, which include
  * pending RAM reads and held output words. No cross-lane latency assumption.
  * CSR park launch waits final fabric response consumption. Release waits no
  * data drain, so unrelated new post-release work cannot strand old control.
  *
  * Command receipts mean actual fixed command consumption, not successful park
  * or admission release. Observations echo epoch AND serial. The caller must
  * join matching observations with fabric-local owners and the real DMA/Home
  * protocol. Old observations must still be consumed. No AON terminal retirement
  * or physical clock-presence/gate proof is provided by these three mailboxes.
  * Common cold reset discards all owners together; unilateral reset is forbidden.
  */
/** The optional final receipt is stronger than the legacy consumed-command
  * receipt: release and its last observation have actually crossed before it.
  * Later PHY/data activity is new work, not an old-epoch idle qualification.
  */
class FixedMacBoundary(depth: Int = 16, heldResponseStorage: Boolean = false,
    deferredReleaseReceipt: Boolean = false, emergencyAdmissionStop: Boolean = false) extends RawModule {
    val fabricClock = IO(Input(Clock()))
    val fixedClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val registers = IO(Flipped(new RegisterPort))
    val macRegisters = IO(new RegisterPort)
    val streams = IO(new ManagedGmacStreams)
    val macStreams = IO(Flipped(new ManagedGmacStreams))
    val command = IO(Flipped(Decoupled(new FixedMacCommand)))
    val consumed = IO(Decoupled(new FixedMacCommand))
    val observation = IO(Decoupled(new FixedMacObservation))
    val txProducersClosed = IO(Input(Bool()))
    val controlProducersClosed = IO(Input(Bool()))
    val admission = IO(Flipped(new EthernetRuntimeAdmissionPort))
    val controlPark = IO(Flipped(new EthernetRuntimeControlParkPort))
    val macIrq = IO(Input(Bool()))
    val irq = IO(Output(Bool()))
    // Each owner output belongs ONLY to the named local clock domain.
    val fabricCsrIdle = IO(Output(Bool()))
    val fabricTxStorageIdle = IO(Output(Bool()))
    val fabricRxConsumersIdle = IO(Output(Bool()))
    val fixedTxConsumersIdle = IO(Output(Bool()))
    val fixedRxStorageIdle = IO(Output(Bool()))
    val emergencyStop = if (emergencyAdmissionStop) Some(IO(Input(Bool()))) else None
    val fixedCsrIdle = if (emergencyAdmissionStop) Some(IO(Output(Bool()))) else None

    private def release(clock: Clock): AsyncReset = {
        val r = Module(new CdcResetRelease)
        r.clockIn := clock
        r.asyncReset := commonReset
        r.resetOut
    }
    private val fabricReset = release(fabricClock)
    private val fixedReset = release(fixedClock)
    private def mailbox(width: Int, from: Clock, to: Clock): CdcMailbox = {
        val m = Module(new CdcMailbox(width))
        m.sourceClock := from
        m.destinationClock := to
        m.commonReset := commonReset
        m
    }
    val csr = Module(new RegisterClockDomainBridge)
    csr.sourceClock := fabricClock
    csr.destinationClock := fixedClock
    csr.commonReset := commonReset
    macRegisters <> csr.destination
    fabricCsrIdle := csr.sourceIdle
    fixedCsrIdle.foreach(_ := csr.destinationIdle && !macRegisters.request.valid && !macRegisters.response.valid)
    private val fatalRxStop = if (emergencyAdmissionStop) {
        val sync = Module(new CdcLevel)
        sync.clockIn := fixedClock; sync.resetIn := fixedReset; sync.levelIn := emergencyStop.get
        Some(sync.levelOut)
    } else None

    // Opt-in only for these four outer lanes. Reuse the existing held-response
    // implementation unchanged: pending reads retain RAM ownership until capture,
    // and destinationIdle includes both pending read and held output ownership.
    private case class StreamStorage(source: DecoupledIO[UInt], destination: DecoupledIO[UInt],
        sourceIdle: Bool, destinationIdle: Bool)
    private def fifo(from: Clock, to: Clock, name: String): StreamStorage = {
        if (heldResponseStorage) {
            val f = Module(new HeldResponseCdcDataFifo((new EthernetAxisWord).getWidth, depth)).suggestName(name)
            f.sourceClock := from
            f.destinationClock := to
            f.commonReset := commonReset
            StreamStorage(f.source, f.destination, f.sourceIdle, f.destinationIdle)
        } else {
            val f = Module(new CdcDataFifo((new EthernetAxisWord).getWidth, depth)).suggestName(name)
            f.sourceClock := from
            f.destinationClock := to
            f.commonReset := commonReset
            StreamStorage(f.source, f.destination, f.sourceIdle, f.destinationIdle)
        }
    }
    private val txData = fifo(fabricClock, fixedClock, "txData")
    private val txControl = fifo(fabricClock, fixedClock, "txControl")
    private val rxData = fifo(fixedClock, fabricClock, "rxData")
    private val rxStatus = fifo(fixedClock, fabricClock, "rxStatus")
    fabricTxStorageIdle := txData.sourceIdle && txControl.sourceIdle
    fixedTxConsumersIdle := txData.destinationIdle && txControl.destinationIdle
    fixedRxStorageIdle := rxData.sourceIdle && rxStatus.sourceIdle
    fabricRxConsumersIdle := rxData.destinationIdle && rxStatus.destinationIdle

    private def connectWord(source: DecoupledIO[EthernetAxisWord], sink: DecoupledIO[UInt], allow: Bool): Unit = {
        sink.valid := source.valid && allow
        sink.bits := source.bits.asUInt
        source.ready := sink.ready && allow
    }
    private def connectWord(source: DecoupledIO[UInt], sink: DecoupledIO[EthernetAxisWord]): Unit = {
        sink.valid := source.valid
        sink.bits := source.bits.asTypeOf(new EthernetAxisWord)
        source.ready := sink.ready
    }
    connectWord(txData.destination, macStreams.txData)
    connectWord(txControl.destination, macStreams.txControl)
    connectWord(macStreams.rxData, rxData.source, true.B)
    connectWord(macStreams.rxStatus, rxStatus.source, true.B)
    connectWord(rxData.destination, streams.rxData)
    connectWord(rxStatus.destination, streams.rxStatus)

    val commands = mailbox((new FixedMacCommand).getWidth, fabricClock, fixedClock)
    val receipts = mailbox((new FixedMacCommand).getWidth, fixedClock, fabricClock)
    val observations = mailbox((new FixedMacObservation).getWidth, fixedClock, fabricClock)
    consumed.valid := receipts.destination.valid
    consumed.bits := receipts.destination.bits.asTypeOf(new FixedMacCommand)
    receipts.destination.ready := consumed.ready
    observation.valid := observations.destination.valid
    observation.bits := observations.destination.bits.asTypeOf(new FixedMacObservation)
    observations.destination.ready := observation.ready

    withClockAndReset(fabricClock, fabricReset) {
        val current = RegInit(0.U.asTypeOf(new FixedMacCommand))
        val pendingReceipt = RegInit(false.B)
        val closingTx = current.txStop || (command.valid && command.bits.txStop)
        // PARK may be offered only after upstream CSR producers are closed,
        // with no unaccepted CSR offer; csrFence also waits for the final reply.
        // Thus its accepting edge cannot accept a CSR request. The accepted
        // command closes admission through current.park on the following cycle.
        // Do not feed command.valid (which may depend on command.ready and the
        // fabric drain witness) back into ordinary CSR ready. That creates a
        // fabric request -> drain -> PARK -> request-ready combinational chain.
        val closingCsr = current.park
        connectWord(streams.txData, txData.source, !closingTx)
        connectWord(streams.txControl, txControl.source, !closingTx)
        csr.source.request.valid := registers.request.valid && !closingCsr
        csr.source.request.bits := registers.request.bits
        registers.request.ready := csr.source.request.ready && !closingCsr
        registers.response <> csr.source.response
        val legal = command.bits.epoch =/= 0.U && command.bits.serial > current.serial &&
            (!command.bits.park || (command.bits.rxStop && command.bits.txStop))
        val txFence = !command.bits.txStop || (txProducersClosed &&
            !streams.txData.valid && !streams.txControl.valid && fabricTxStorageIdle)
        val csrFence = !command.bits.park || (controlProducersClosed &&
            !registers.request.valid && csr.sourceIdle)
        commands.source.valid := command.valid && !pendingReceipt && legal && txFence && csrFence
        commands.source.bits := command.bits.asUInt
        command.ready := commands.source.ready && !pendingReceipt && legal && txFence && csrFence
        when(command.fire) { current := command.bits; pendingReceipt := true.B }
        when(consumed.fire) {
            assert(pendingReceipt && consumed.bits.asUInt === current.asUInt,
                "fixed MAC receipt must consume the exact outstanding command")
            pendingReceipt := false.B
        }
        when(command.valid && !pendingReceipt) {
            assert(legal, "fixed MAC command needs nonzero epoch and increasing serial; park requires both stops")
            when(command.bits.txStop) {
                assert(txProducersClosed && !streams.txData.valid && !streams.txControl.valid,
                    "fixed MAC TX close requires completed upstream producers")
            }
            when(command.bits.park) {
                assert(controlProducersClosed && !registers.request.valid,
                    "fixed MAC park requires real upstream held and no unaccepted CSR offer")
            }
        }
    }
    withClockAndReset(fixedClock, fixedReset) {
        val current = RegInit(0.U.asTypeOf(new FixedMacCommand))
        // Legacy standalone users retain their immediate consumed receipt.
        // The platform opt-in instead retires release only after its actual
        // released snapshot has been consumed. No fourth mailbox/epoch owner.
        val releasePending = if (deferredReleaseReceipt) Some(RegInit(false.B)) else None
        val releaseSnapshotSent = if (deferredReleaseReceipt) Some(RegInit(false.B)) else None
        if (deferredReleaseReceipt) {
            val incoming = commands.destination.bits.asTypeOf(new FixedMacCommand)
            val isRelease = !incoming.rxStop && !incoming.txStop && !incoming.park
            commands.destination.ready := receipts.source.ready && !releasePending.get
            receipts.source.valid := (commands.destination.valid && !releasePending.get && !isRelease) ||
                (releasePending.get && releaseSnapshotSent.get && observations.sourceIdle && commands.destinationIdle)
            receipts.source.bits := Mux(releasePending.get, current.asUInt, commands.destination.bits)
            when(receipts.source.fire && releasePending.get) { releasePending.get := false.B }
            when(commands.destination.fire) {
                releasePending.get := isRelease
                releaseSnapshotSent.get := false.B
            }
        } else {
            commands.destination.ready := receipts.source.ready
            receipts.source.valid := commands.destination.valid
            receipts.source.bits := commands.destination.bits
        }
        val txApplied = RegInit(false.B)
        val parkApplied = RegInit(false.B)
        when(commands.destination.fire) {
            val incoming = commands.destination.bits.asTypeOf(new FixedMacCommand)
            current := incoming
            when(!incoming.txStop) { txApplied := false.B }
            when(!incoming.park) { parkApplied := false.B }
        }.otherwise {
            when(current.txStop && fixedTxConsumersIdle) { txApplied := true.B }
            when(current.park && txApplied && admission.txDrained && admission.rxDrained &&
                fixedTxConsumersIdle && csr.destinationIdle) { parkApplied := true.B }
        }
        // Once applied, retain votes until actual fixed consumption of release.
        // New post-release fabric data can outrun the independent command lane;
        // it must not withdraw the OLD vote by making a local idle predicate low.
        // Emergency loss-of-clock isolation only closes NEW RX admission.
        // Accepted stream/CSR owners and their replies continue unchanged.
        admission.rxStopRequest := current.rxStop || fatalRxStop.getOrElse(false.B)
        admission.txStopRequest := txApplied
        controlPark.request := parkApplied
        val snapshot = Wire(new FixedMacObservation)
        snapshot.command := current
        snapshot.txDrained := current.txStop && txApplied && admission.txDrained && fixedTxConsumersIdle
        snapshot.rxDrained := current.rxStop && admission.rxDrained && fixedRxStorageIdle
        snapshot.released := !current.rxStop && !current.txStop && !current.park &&
            admission.released && controlPark.released
        snapshot.parked := current.park && parkApplied && controlPark.parked
        snapshot.csrDrained := controlPark.csrDrained && csr.destinationIdle
        snapshot.configDrained := controlPark.configDrained
        snapshot.mdioDrained := controlPark.mdioDrained
        snapshot.phyParked := controlPark.phyParked
        snapshot.mediaSettled := controlPark.mediaSettled
        snapshot.phyFault := controlPark.phyFault
        snapshot.statisticsPending := controlPark.statisticsPending
        observations.source.valid := current.epoch =/= 0.U
        observations.source.bits := snapshot.asUInt
        if (deferredReleaseReceipt) {
            // Do not publish the old command on the edge consuming a new one.
            // Once final release is sent, stay quiet until another real command;
            // clearing this on receipt.fire would recreate an old snapshot owner.
            observations.source.valid := current.epoch =/= 0.U && !commands.destination.valid &&
                !releaseSnapshotSent.get
            when(observations.source.fire && releasePending.get && snapshot.released) {
                releaseSnapshotSent.get := true.B
            }
        }
        val launchedIrq = RegNext(macIrq, false.B)
        val sync = Module(new CdcLevel)
        sync.clockIn := fabricClock
        sync.resetIn := fabricReset
        sync.levelIn := launchedIrq
        irq := sync.levelOut
    }
}

/** Standalone real MAC composition. Not selected by any production platform.
  * All source-domain logic (including PHY/MDIO/media/watchdog/CSR/adapter) runs
  * on the MAC's EXISTING continuous 125 MHz leaf, with matching cpuHz metadata.
  * No new MMCM, clock buffer, DRP path, reset epoch or software timing rewrite.
  */
class FixedSourceManagedGmac(aonHz: Int = 50000000, hardwareClocks: Boolean = true,
    networkDmaConfig: NetworkDmaConfig = NetworkDmaConfig.Default, txFrameSlots: Int = 2,
    balancedRawClock: Boolean = false, heldResponseStorage: Boolean = false) extends RawModule {
    val fabricClock = IO(Input(Clock()))
    val rawTxClock = IO(Input(Clock()))
    val rawRxClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val registers = IO(Flipped(new RegisterPort))
    val streams = IO(new ManagedGmacStreams)
    val command = IO(Flipped(Decoupled(new FixedMacCommand)))
    val consumed = IO(Decoupled(new FixedMacCommand))
    val observation = IO(Decoupled(new FixedMacObservation))
    val txProducersClosed = IO(Input(Bool()))
    val controlProducersClosed = IO(Input(Bool()))
    val fabricCsrIdle = IO(Output(Bool()))
    val fabricTxStorageIdle = IO(Output(Bool()))
    val fabricRxConsumersIdle = IO(Output(Bool()))
    val control = IO(Flipped(Vec(2, new ClockResourceControl)))
    val rawRgmiiRxRise = IO(Input(UInt(5.W)))
    val rawRgmiiRxFall = IO(Input(UInt(5.W)))
    val rgmiiTxRise = IO(Output(UInt(5.W)))
    val rgmiiTxFall = IO(Output(UInt(5.W)))
    val gmiiTxData = IO(Output(UInt(8.W)))
    val gmiiTxEnable = IO(Output(Bool()))
    val gmiiTxError = IO(Output(Bool()))
    val mdc = IO(Output(Bool()))
    val mdioIn = IO(Input(Bool()))
    val mdioOut = IO(Output(Bool()))
    val mdioOe = IO(Output(Bool()))
    val irq = IO(Output(Bool()))
    val linkUp = IO(Output(Bool()))
    val appliedSpeed = IO(Output(UInt(2.W)))
    val mediaPending = IO(Output(Bool()))
    protected def buildMac(): TriSpeedManagedGmac =
        new TriSpeedManagedGmac(125000000, aonHz, hardwareClocks = hardwareClocks,
            networkDmaConfig = networkDmaConfig, txFrameSlots = txFrameSlots,
            balancedRawClock = balancedRawClock, runtimeAdmission = true, runtimeControlPark = true,
            exportContinuousClock = true)
    val mac = Module(buildMac())
    val boundary = Module(new FixedMacBoundary(heldResponseStorage = heldResponseStorage))
    mac.rawTxClock := rawTxClock
    mac.rawRxClock := rawRxClock
    mac.sourceClock := mac.continuousClock.get
    mac.commonReset := commonReset
    boundary.fabricClock := fabricClock
    boundary.fixedClock := mac.continuousClock.get
    boundary.commonReset := commonReset
    boundary.registers <> registers
    boundary.macRegisters <> mac.registers
    boundary.streams <> streams
    boundary.macStreams <> mac.streams
    boundary.command <> command
    consumed <> boundary.consumed
    observation <> boundary.observation
    boundary.txProducersClosed := txProducersClosed
    boundary.controlProducersClosed := controlProducersClosed
    boundary.admission <> mac.runtimeAdmissionPort.get
    boundary.controlPark <> mac.controlPark.get
    fabricCsrIdle := boundary.fabricCsrIdle
    fabricTxStorageIdle := boundary.fabricTxStorageIdle
    fabricRxConsumersIdle := boundary.fabricRxConsumersIdle
    boundary.macIrq := mac.irq
    irq := boundary.irq
    mac.control <> control
    mac.rawRgmiiRxRise := rawRgmiiRxRise
    mac.rawRgmiiRxFall := rawRgmiiRxFall
    rgmiiTxRise := mac.rgmiiTxRise
    rgmiiTxFall := mac.rgmiiTxFall
    gmiiTxData := mac.gmiiTxData
    gmiiTxEnable := mac.gmiiTxEnable
    gmiiTxError := mac.gmiiTxError
    mac.mdioIn := mdioIn
    mdc := mac.mdc
    mdioOut := mac.mdioOut
    mdioOe := mac.mdioOe
    linkUp := mac.linkUp
    appliedSpeed := mac.appliedSpeed
    mediaPending := mac.mediaPending
}
