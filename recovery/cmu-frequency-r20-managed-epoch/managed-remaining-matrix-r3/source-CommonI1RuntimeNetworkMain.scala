package platform

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.axi.Axi4MemoryPort
import soc.ip.bus.{CdcLevel, CdcResetRelease, RegisterResponse}
import soc.ip.ethernet._
import soc.platform._

/** Passive observations of the actual fabric packet-DMA owner. No second DMA,
  * control master, memory responder, or synthesized completion is introduced.
  */
class RuntimePacketMemoryObservations extends Bundle {
    val dmaActive = Output(Bool())
    val memoryRequestValid = Output(Bool())
    val memoryRequestReady = Output(Bool())
    val memoryRequestFire = Output(Bool())
    val memoryRequestAddress = Output(UInt(64.W))
    val memoryRequestData = Output(UInt(64.W))
    val memoryRequestWrite = Output(Bool())
    val memoryRequestSize = Output(UInt(3.W))
    val memoryRequestByteEnable = Output(UInt(8.W))
    val memoryResponseValid = Output(Bool())
    val memoryResponseReady = Output(Bool())
    val memoryResponseFire = Output(Bool())
    val memoryResponseData = Output(UInt(64.W))
    val memoryResponseError = Output(Bool())
    val controlRequestValid = Output(Bool())
    val controlRequestReady = Output(Bool())
    val controlRequestFire = Output(Bool())
    val controlRequestAddress = Output(UInt(64.W))
    val controlRequestData = Output(UInt(64.W))
    val controlRequestWrite = Output(Bool())
    val controlResponseValid = Output(Bool())
    val controlResponseReady = Output(Bool())
    val controlResponseFire = Output(Bool())
    val controlResponseError = Output(Bool())
}

class RuntimeNetworkTestFabric(boundaryParams: CommonCpuTilePortParams, words: Int, fixedTimer: Boolean = false)
    extends RuntimeDebugTestFabric(boundaryParams, words, externalMemory = true, networkAdmission = true, fixedTimer = fixedTimer) {
    val packetObserve = IO(new RuntimePacketMemoryObservations)
    val packetOwner = packetDma.get
    packetObserve.dmaActive := packetOwner.io.active
    packetObserve.memoryRequestValid := packetOwner.io.memory.request.valid
    packetObserve.memoryRequestReady := packetOwner.io.memory.request.ready
    packetObserve.memoryRequestFire := packetOwner.io.memory.request.fire
    packetObserve.memoryRequestAddress := packetOwner.io.memory.request.bits.address
    packetObserve.memoryRequestData := packetOwner.io.memory.request.bits.data
    packetObserve.memoryRequestWrite := packetOwner.io.memory.request.bits.write
    packetObserve.memoryRequestSize := packetOwner.io.memory.request.bits.size
    packetObserve.memoryRequestByteEnable := packetOwner.io.memory.request.bits.byteEnable
    packetObserve.memoryResponseValid := packetOwner.io.memory.response.valid
    packetObserve.memoryResponseReady := packetOwner.io.memory.response.ready
    packetObserve.memoryResponseFire := packetOwner.io.memory.response.fire
    packetObserve.memoryResponseData := packetOwner.io.memory.response.bits.data
    packetObserve.memoryResponseError := packetOwner.io.memory.response.bits.error
    packetObserve.controlRequestValid := packetOwner.io.control.request.valid
    packetObserve.controlRequestReady := packetOwner.io.control.request.ready
    packetObserve.controlRequestFire := packetOwner.io.control.request.fire
    packetObserve.controlRequestAddress := packetOwner.io.control.request.bits.address
    packetObserve.controlRequestData := packetOwner.io.control.request.bits.data
    packetObserve.controlRequestWrite := packetOwner.io.control.request.bits.write
    packetObserve.controlResponseValid := packetOwner.io.control.response.valid
    packetObserve.controlResponseReady := packetOwner.io.control.response.ready
    packetObserve.controlResponseFire := packetOwner.io.control.response.fire
    packetObserve.controlResponseError := packetOwner.io.control.response.bits.error
}

class RuntimeNetworkObservations extends RuntimePacketMemoryObservations {
    val holdRxStatusLast = Input(Bool())
    val holdTxControlLast = Input(Bool())
    val holdTxDataLast = Input(Bool())
    val holdAxiReadResponse = Input(Bool())
    val holdAxiWriteResponse = Input(Bool())
    val axiReadResponseBlocked = Output(Bool())
    val axiWriteResponseBlocked = Output(Bool())
    val axiReadResponseFire = Output(Bool())
    val axiWriteResponseFire = Output(Bool())
    val gmiiRxData = Input(UInt(8.W))
    val gmiiRxValid = Input(Bool())
    val gmiiRxError = Input(Bool())
    val gmiiTxData = Output(UInt(8.W))
    val gmiiTxEnable = Output(Bool())
    val gmiiTxError = Output(Bool())
    val retirementPermit = Output(Bool())
    val epochBusy = Output(Bool())
    val epochHeld = Output(Bool())
    val epochHeldValue = Output(UInt(8.W))
    val runtimePause = Output(Bool())
    val rxStopRequest = Output(Bool())
    val txStopRequest = Output(Bool())
    val dmaTxIdle = Output(Bool())
    val dmaOwnersIdle = Output(Bool())
    val rxDrained = Output(Bool())
    val txDrained = Output(Bool())
    val released = Output(Bool())
    val rxAdmissionClosed = Output(Bool())
    val rxAccepted = Output(Bool())
    val rxDropped = Output(Bool())
    val rxDropReasons = Output(UInt(8.W))
    val rxBadFcs = Output(Bool())
    val txBusy = Output(Bool())
    val txDone = Output(Bool())
    val rxStatusLastBlocked = Output(Bool())
    val txControlLastBlocked = Output(Bool())
    val txDataLastBlocked = Output(Bool())
    val rxDataFire = Output(Bool())
    val rxDataLastFire = Output(Bool())
    val rxStatusFire = Output(Bool())
    val rxStatusData = Output(UInt(32.W))
    val rxStatusLastFire = Output(Bool())
    val txControlFire = Output(Bool())
    val txDataFire = Output(Bool())
    val txDataLastFire = Output(Bool())
    val rxDestinationIdle = Output(Bool())
    val txSourceIdle = Output(Bool())
}

/** Real I1/cache + CPU CDC + r10 epoch + r15 debug + r16 packet admission.
  * The sole packet DMA uses the production Atomic/Home/DDR-manager path.
  * An explicit testbench RAM services its external AXI channels. Test gates
  * backpressure offered AXI responses and real stream tails, never fabricate
  * acknowledgements. RX, TX, debug, CPU, fabric and AON remain independently
  * clocked; PHY management and continuously running statistics are excluded.
  */
class CommonI1RuntimeNetworkFixture extends CommonI1RuntimeDebugFixture(512) {
    override def makeFabric(): CommonMachineFabric = new RuntimeNetworkTestFabric(boundary, testRomWords)
    val rxClock = IO(Input(Clock()))
    val txClock = IO(Input(Clock()))
    val ddrAxi = IO(new Axi4MemoryPort(32, fabric.fpga.ddr.axiIdWidth))
    val packet = IO(new RuntimeNetworkObservations)
    val packetLineProbes = IO(Output(UInt(32.W)))
    val packetLineProbeDataBeats = IO(Output(UInt(32.W)))
    val packetTxLineProbes = IO(Output(UInt(32.W)))
    val packetTxLineProbeDataBeats = IO(Output(UInt(32.W)))
    val packetObservations = fabric.asInstanceOf[RuntimeNetworkTestFabric].packetObserve
    for ((name, field) <- packetObservations.elements) {
        packet.elements(name) := field
    }

    // Test-only elaboration hooks. The default omitted-control and packet plane
    // remain exact; a managed integration fixture replaces, never supplements,
    // these owners before connecting the real fabric streams.
    protected def wireMacRegisters(): Unit = {
        // MAC configuration, PHY/MDIO and statistics are outside this fixture.
        // The required decoded Ethernet CSR window is explicitly unavailable:
        // each real request owns a registered error reply, stable under backpressure.
        // No invented MAC state or successful peripheral acknowledgement is exposed.
        val unavailableMacReplies = withClockAndReset(fabricClock, fabricRelease.resetOut) {
            Module(new Queue(new RegisterResponse, 1, pipe = false, flow = false))
        }
        val macRegisters = fabric.io.ethernetRegisters.get
        unavailableMacReplies.io.enq.valid := macRegisters.request.valid
        unavailableMacReplies.io.enq.bits.data := 0.U
        unavailableMacReplies.io.enq.bits.error := true.B
        macRegisters.request.ready := unavailableMacReplies.io.enq.ready
        macRegisters.response <> unavailableMacReplies.io.deq
        withClockAndReset(fabricClock, fabricRelease.resetOut) {
            assert(!macRegisters.request.fire,
                "fixture guest accessed omitted MAC configuration/PHY/MDIO/statistics registers")
        }
    }
    wireMacRegisters()

    // Preserve the actual selected four-slot/two-write manager. In particular,
    // W acceptance is not completion; only its eventual real B retires it.
    val memory = fabric.io.ddrAxi.get
    ddrAxi <> memory
    memory.r.valid := ddrAxi.r.valid && !packet.holdAxiReadResponse
    ddrAxi.r.ready := memory.r.ready && !packet.holdAxiReadResponse
    memory.b.valid := ddrAxi.b.valid && !packet.holdAxiWriteResponse
    ddrAxi.b.ready := memory.b.ready && !packet.holdAxiWriteResponse
    packet.axiReadResponseBlocked := ddrAxi.r.valid && packet.holdAxiReadResponse
    packet.axiWriteResponseBlocked := ddrAxi.b.valid && packet.holdAxiWriteResponse
    packet.axiReadResponseFire := memory.r.fire
    packet.axiWriteResponseFire := memory.b.fire

    val network = withClockAndReset(fabricClock, fabricRelease.resetOut) {
        Module(new CommonNetworkRuntimeSequencer(boundary))
    }
    // r10 prepare -> real network drain -> r15 debug drain -> real fabric/CPU.
    network.io.upstreamPrepare <> runtime.io.externalMaintenance
    sequencer.upstreamPrepare <> network.io.downstreamPrepare
    fabric.io.networkPause.get := network.io.dmaPause
    fabric.io.networkAdmissionHeld.get := network.io.held
    network.io.dmaTxIdle := fabric.io.networkTxIdle.get
    network.io.dmaOwnersIdle := fabric.io.networkOwnersIdle.get
    network.io.terminalConsumedAtAon := runtime.io.terminalConsumedAtAon.get
    network.io.retired := runtime.io.runtimeComplete.fire
    network.io.fault := sequencer.fault
    runtime.io.retirementPermit.get := sequencer.retirementPermit && network.io.retirementPermit
    packet.retirementPermit := network.io.retirementPermit
    packet.epochBusy := network.io.busy
    packet.epochHeld := network.io.held.valid
    packet.epochHeldValue := network.io.held.bits
    packet.runtimePause := network.io.dmaPause
    packet.rxStopRequest := network.io.rxStop
    packet.txStopRequest := network.io.txStop
    packet.dmaTxIdle := fabric.io.networkTxIdle.get
    packet.dmaOwnersIdle := fabric.io.networkOwnersIdle.get

    protected def wirePacketPlane(): Unit = {
        val rxRelease = Module(new CdcResetRelease)
        rxRelease.clockIn := rxClock
        rxRelease.asyncReset := commonColdReset
        val txRelease = Module(new CdcResetRelease)
        txRelease.clockIn := txClock
        txRelease.asyncReset := commonColdReset
        val maxFrameBytes = fabric.fpga.network.maxFrameBytes
        val adapter = withClockAndReset(fabricClock, fabricRelease.resetOut) {
            Module(new EthernetDmaFrameAdapter(managed = true))
        }
        val rx = withClockAndReset(rxClock, rxRelease.resetOut) {
            Module(new GmiiFrameRx(maxFrameBytes, admissionStop = true,
                frameSlots = fabric.fpga.network.macRxSlots, diagnostics = true))
        }
        val tx = withClockAndReset(txClock, txRelease.resetOut) {
            Module(new GmiiFrameTx(maxFrameBytes))
        }
        val rxBridge = Module(new EthernetFrameClockBridge(4))
        rxBridge.sourceClock := rxClock
        rxBridge.destinationClock := fabricClock
        rxBridge.commonReset := commonColdReset
        val txBridge = Module(new EthernetFrameClockBridge(4))
        txBridge.sourceClock := fabricClock
        txBridge.destinationClock := txClock
        txBridge.commonReset := commonColdReset
        val stop = Module(new EthernetRxAdmissionStop)
        stop.sourceClock := fabricClock
        stop.destinationClock := rxClock
        stop.commonReset := commonColdReset
        stop.requested := network.io.rxStop
        stop.destinationFrameIdle := !rx.io.ownedBusy.get
        stop.destinationFifoIdle := rxBridge.sourceIdle
        stop.sourceDrained := rxBridge.destinationIdle && adapter.io.rxIdle
        rx.io.stopNewFrames.get := stop.stopNewFrames
        rx.io.gmiiData := packet.gmiiRxData
        rx.io.gmiiValid := packet.gmiiRxValid
        rx.io.gmiiError := packet.gmiiRxError
        rx.io.enable := true.B
        rx.io.promiscuous := true.B
        rx.io.broadcastEnable := true.B
        rx.io.macAddress := "h020000000001".U
        rxBridge.source <> rx.io.frame
        adapter.io.rxFrame <> rxBridge.destination

        val streams = fabric.io.ethernetStreams.get
        streams.rxData <> adapter.io.rxData
        streams.rxStatus <> adapter.io.rxStatus
        val statusAllow = !packet.holdRxStatusLast || !adapter.io.rxStatus.bits.last
        streams.rxStatus.valid := adapter.io.rxStatus.valid && statusAllow
        adapter.io.rxStatus.ready := streams.rxStatus.ready && statusAllow
        adapter.io.txData <> streams.txData
        adapter.io.txControl <> streams.txControl
        val controlAllow = !packet.holdTxControlLast || !streams.txControl.bits.last
        adapter.io.txControl.valid := streams.txControl.valid && controlAllow
        streams.txControl.ready := adapter.io.txControl.ready && controlAllow
        val dataAllow = !packet.holdTxDataLast || !streams.txData.bits.last
        adapter.io.txData.valid := streams.txData.valid && dataAllow
        streams.txData.ready := adapter.io.txData.ready && dataAllow
        adapter.io.stopNewTx.get := network.io.txStop
        txBridge.source <> adapter.io.txFrame
        tx.io.frame <> txBridge.destination
        tx.io.enable := true.B

        // TX proof includes serializer and IFG ownership, not merely last FIFO pop.
        val txLocalIdle = withClockAndReset(txClock, txRelease.resetOut) {
            RegNext(txBridge.destinationIdle && !tx.io.busy, false.B)
        }
        val wireIdle = Module(new CdcLevel)
        wireIdle.clockIn := fabricClock
        wireIdle.resetIn := fabricRelease.resetOut
        wireIdle.levelIn := txLocalIdle
        packet.txDrained := adapter.io.txIdle && txBridge.sourceIdle && wireIdle.levelOut
        packet.rxDrained := stop.drained
        packet.released := !network.io.rxStop && !network.io.txStop && stop.settled
        network.io.macTxDrained := packet.txDrained
        network.io.macRxDrained := stop.drained
        network.io.macReleased := packet.released
        packet.rxAdmissionClosed := stop.stopNewFrames
        packet.rxAccepted := rx.io.accepted
        packet.rxDropped := rx.io.dropped
        packet.rxDropReasons := rx.io.dropReasons.get
        packet.rxBadFcs := rx.io.badFcs
        packet.txBusy := tx.io.busy
        packet.txDone := tx.io.done
        packet.gmiiTxData := tx.io.gmiiData
        packet.gmiiTxEnable := tx.io.gmiiEnable
        packet.gmiiTxError := tx.io.gmiiError
        packet.rxStatusLastBlocked := adapter.io.rxStatus.valid && adapter.io.rxStatus.bits.last && !statusAllow
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
        packet.rxDestinationIdle := rxBridge.destinationIdle
        packet.txSourceIdle := txBridge.sourceIdle
    }
    wirePacketPlane()

    // Guest SW dirties bytes 60..63 of the same line receiving a real 60-byte RX
    // body. The DMA's final byte enables must preserve this dirty CPU neighbor.
    withClockAndReset(cpuClock, cpuRelease.resetOut) {
        val probes = RegInit(0.U(32.W))
        val dataBeats = RegInit(0.U(32.W))
        val txProbes = RegInit(0.U(32.W))
        val txDataBeats = RegInit(0.U(32.W))
        probes := probes + PopCount(tile.io.bus.coherent.map(c =>
            c.b.fire && c.b.bits.address === "h80203000".U))
        dataBeats := dataBeats + PopCount(tile.io.bus.coherent.map(c =>
            c.c.fire && c.c.bits.opcode === 5.U && c.c.bits.address === "h80203000".U))
        txProbes := txProbes + PopCount(tile.io.bus.coherent.map(c =>
            c.b.fire && c.b.bits.address === "h80204000".U))
        txDataBeats := txDataBeats + PopCount(tile.io.bus.coherent.map(c =>
            c.c.fire && c.c.bits.opcode === 5.U && c.c.bits.address === "h80204000".U))
        packetLineProbes := probes
        packetLineProbeDataBeats := dataBeats
        packetTxLineProbes := txProbes
        packetTxLineProbeDataBeats := txDataBeats
    }
}

object CommonI1RuntimeNetworkNativeMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new CommonI1RuntimeNetworkFixture, Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
