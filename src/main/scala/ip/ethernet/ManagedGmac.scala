package soc.ip.ethernet

import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.ip.bus._
import soc.ip.clock._
import soc.ip.dma.EthernetAxisWord

/** One-credit internal RegisterPort to original native64 TL-UL CSR frontend.
  * No atomics/bursts; preserve held lane until D consumes the ordered reply.
  * CPU/MMIO need not share either managed media clock.
  */
class RegisterGmacControl(base: BigInt, tlParams: TLParams) extends Module {
    val io = IO(new Bundle {
        val registers = Flipped(new RegisterPort)
        val tl = new TLBundle(tlParams)
    })
    val busy = RegInit(false.B)
    val lane = Reg(UInt(3.W))
    val request = io.registers.request.bits
    io.tl.a.valid := io.registers.request.valid && !busy
    io.tl.a.bits := 0.U.asTypeOf(io.tl.a.bits)
    io.tl.a.bits.opcode := Mux(request.write, TLOpcode.PutPartialData, TLOpcode.Get)
    io.tl.a.bits.address := Mux(request.size <= 3.U, request.address, (base + 4096).U)
    io.tl.a.bits.size := Mux(request.size <= 3.U, request.size, 3.U)
    io.tl.a.bits.data := (request.data << Cat(request.address(2, 0), 0.U(3.W)))(63, 0)
    io.tl.a.bits.mask := (request.byteEnable << request.address(2, 0))(7, 0)
    io.registers.request.ready := !busy && io.tl.a.ready
    when(io.tl.a.fire) { busy := true.B; lane := request.address(2, 0) }
    io.registers.response.valid := busy && io.tl.d.valid
    io.registers.response.bits.data := io.tl.d.bits.data >> Cat(lane, 0.U(3.W))
    io.registers.response.bits.error := io.tl.d.bits.denied || io.tl.d.bits.corrupt
    io.tl.d.ready := busy && io.registers.response.ready
    when(io.tl.d.fire) { busy := false.B }
    io.tl.b.ready := true.B
    io.tl.c.valid := false.B
    io.tl.c.bits := 0.U.asTypeOf(io.tl.c.bits)
    io.tl.e.valid := false.B
    io.tl.e.bits := 0.U.asTypeOf(io.tl.e.bits)
}

class ManagedGmacStreams extends Bundle {
    val txData = Flipped(Decoupled(new EthernetAxisWord))
    val txControl = Flipped(Decoupled(new EthernetAxisWord))
    val rxData = Decoupled(new EthernetAxisWord)
    val rxStatus = Decoupled(new EthernetAxisWord)
}

/** Native1G/full-duplex managed endpoint with actual framing/DMA adapter.
  * CPU control stays on. TX/RX stop independently only after frame/FIFO/config/
  * statistics/adapter tails AND CPU admission handshake have completely drained.
  * PHY raw RX capture stays on; fixed ingress delay preserves the first frame.
  * This is a GMII boundary, NOT a completed board RGMII/PHY or Linux driver.
  */
class ManagedGmac(cpuHz: Int = 100000000, aonHz: Int = 50000000,
    mediaHz: Int = 125000000, hardwareClocks: Boolean = true) extends RawModule {
    require(mediaHz == 125000000, "current frame engines support1G/full-duplex only")
    val sourceClock = IO(Input(Clock()))
    val rawTxClock = IO(Input(Clock()))
    val rawRxClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val registers = IO(Flipped(new RegisterPort))
    val streams = IO(new ManagedGmacStreams)
    val control = IO(Flipped(Vec(2, new ClockResourceControl)))
    val txClock = IO(Output(Clock()))
    val rxClock = IO(Output(Clock()))
    val gmiiTxData = IO(Output(UInt(8.W)))
    val gmiiTxEnable = IO(Output(Bool()))
    val gmiiTxError = IO(Output(Bool()))
    val gmiiRxData = IO(Input(UInt(8.W)))
    val gmiiRxValid = IO(Input(Bool()))
    val gmiiRxError = IO(Input(Bool()))
    val linkUp = IO(Input(Bool()))
    val mdc = IO(Output(Bool()))
    val mdioIn = IO(Input(Bool()))
    val mdioOut = IO(Output(Bool()))
    val mdioOe = IO(Output(Bool()))
    val irq = IO(Output(Bool()))
    val localIdle = IO(Output(Vec(2, Bool())))
    val cpuRelease = Module(new CdcResetRelease)
    cpuRelease.clockIn := sourceClock
    cpuRelease.asyncReset := commonReset
    def gated(raw: Clock, index: Int): Clock = if (hardwareClocks) {
        val gate = Module(new ManagedClockBuffer)
        gate.rawClock := raw
        gate.commonReset := commonReset
        gate.enable := control(index).clockEnable
        gate.managedClock
    } else raw
    val txManaged = gated(rawTxClock, 0)
    val rxManaged = gated(rawRxClock, 1)
    txClock := txManaged
    rxClock := rxManaged
    val txRelease = Module(new CdcResetRelease)
    txRelease.clockIn := txManaged
    txRelease.asyncReset := commonReset
    val rxRelease = Module(new CdcResetRelease)
    rxRelease.clockIn := rxManaged
    rxRelease.asyncReset := commonReset
    val txQ = ManagedPeripheralSupport.level(control(0).quiesce, sourceClock, cpuRelease.resetOut)
    val txIso = ManagedPeripheralSupport.level(control(0).isolate, sourceClock, cpuRelease.resetOut)
    val rxQ = ManagedPeripheralSupport.level(control(1).quiesce, sourceClock, cpuRelease.resetOut)
    val adapter = withClockAndReset(sourceClock, cpuRelease.resetOut) { Module(new EthernetDmaFrameAdapter(true)) }
    adapter.io.txData <> streams.txData
    adapter.io.txControl <> streams.txControl
    streams.rxData <> adapter.io.rxData
    streams.rxStatus <> adapter.io.rxStatus
    adapter.io.stopNewTx.get := txQ || txIso
    val txFifo = Module(new EthernetFrameClockBridge(16))
    txFifo.sourceClock := sourceClock
    txFifo.destinationClock := txManaged
    txFifo.commonReset := commonReset
    txFifo.source <> adapter.io.txFrame
    val rxFifo = Module(new EthernetFrameClockBridge(16))
    rxFifo.sourceClock := rxManaged
    rxFifo.destinationClock := sourceClock
    rxFifo.commonReset := commonReset
    adapter.io.rxFrame <> rxFifo.destination
    val tx = withClockAndReset(txManaged, txRelease.resetOut) { Module(new GmiiFrameTx) }
    val rx = withClockAndReset(rxManaged, rxRelease.resetOut) { Module(new GmiiFrameRx(admissionStop = true)) }
    tx.io.frame <> txFifo.destination
    rxFifo.source <> rx.io.frame
    val txConfig = Module(new EthernetConfigClockBridge)
    val rxConfig = Module(new EthernetConfigClockBridge)
    txConfig.sourceClock := sourceClock
    txConfig.destinationClock := txManaged
    txConfig.commonReset := commonReset
    rxConfig.sourceClock := sourceClock
    rxConfig.destinationClock := rxManaged
    rxConfig.commonReset := commonReset
    val txStats = Module(new CdcCounterBank(3))
    val rxStats = Module(new CdcCounterBank(4))
    txStats.sourceClock := txManaged
    txStats.destinationClock := sourceClock
    txStats.commonReset := commonReset
    rxStats.sourceClock := rxManaged
    rxStats.destinationClock := sourceClock
    rxStats.commonReset := commonReset
    txStats.increment(0) := tx.io.done
    txStats.increment(1) := tx.io.rejected
    txStats.increment(2) := Mux(tx.io.done, tx.io.bytes, 0.U)
    rxStats.increment(0) := rx.io.accepted
    rxStats.increment(1) := rx.io.dropped
    rxStats.increment(2) := rx.io.badFcs
    rxStats.increment(3) := Mux(rx.io.accepted, rx.io.bytes, 0.U)
    txStats.delta.ready := true.B
    rxStats.delta.ready := true.B
    val tlParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4)
    val config = GmacParams(controlClockHz = cpuHz, aggregateStats = true, rxAdmissionStop = true)
    val frontend = withClockAndReset(sourceClock, cpuRelease.resetOut) {
        Module(new RegisterGmacControl(config.base, tlParams))
    }
    val csr = withClockAndReset(sourceClock, cpuRelease.resetOut) {
        Module(new TileLinkGmacControl(config, tlParams))
    }
    frontend.io.registers <> registers
    csr.io.tl <> frontend.io.tl
    val port = csr.io.ports.head
    val rxStop = Module(new EthernetRxAdmissionStop)
    rxStop.sourceClock := sourceClock
    rxStop.destinationClock := rxManaged
    rxStop.commonReset := commonReset
    rxStop.requested := port.rxStopRequest.get
    rxStop.sourceDrained := adapter.io.rxIdle && rxFifo.destinationIdle
    rxStop.destinationFrameIdle := !rx.io.ownedBusy.get
    rxStop.destinationFifoIdle := rxFifo.sourceIdle
    rx.io.stopNewFrames.get := rxStop.stopNewFrames
    port.rxStopDrained.get := rxStop.drained
    val currentConfig = Wire(new EthernetConfigSnapshot)
    currentConfig.macAddress := port.macAddress
    currentConfig.txEnable := port.txEnable
    currentConfig.rxEnable := port.rxEnable
    currentConfig.promiscuous := port.promiscuous
    currentConfig.broadcastEnable := port.broadcastEnable
    val sentConfig = withClockAndReset(sourceClock, cpuRelease.resetOut) { RegInit(0.U(52.W)) }
    val dirty = currentConfig.asUInt =/= sentConfig
    txConfig.source.valid := dirty && rxConfig.source.ready
    rxConfig.source.valid := dirty && txConfig.source.ready
    txConfig.source.bits := currentConfig
    rxConfig.source.bits := currentConfig
    withClockAndReset(sourceClock, cpuRelease.resetOut) {
        when(txConfig.source.fire && rxConfig.source.fire) { sentConfig := currentConfig.asUInt }
    }
    txConfig.destination.ready := !tx.io.busy
    // With producer admission closed, unrelated physical traffic is discarded
    // and owns no payload/configuration. It cannot postpone shutdown forever.
    val rxConfigurationIdle = !rx.io.busy || (rxStop.stopNewFrames && !rx.io.ownedBusy.get)
    rxConfig.destination.ready := rxConfigurationIdle
    val txImage = withClockAndReset(txManaged, txRelease.resetOut) {
        val image = RegInit(0.U.asTypeOf(new EthernetConfigSnapshot))
        when(txConfig.destination.fire) { image := txConfig.destination.bits }
        image
    }
    val rxImage = withClockAndReset(rxManaged, rxRelease.resetOut) {
        val image = RegInit(0.U.asTypeOf(new EthernetConfigSnapshot))
        when(rxConfig.destination.fire) { image := rxConfig.destination.bits }
        image
    }
    tx.io.enable := txImage.txEnable
    rx.io.enable := rxImage.rxEnable
    rx.io.promiscuous := rxImage.promiscuous
    rx.io.broadcastEnable := rxImage.broadcastEnable
    rx.io.macAddress := rxImage.macAddress
    val ingress = Module(new PeripheralWakeDelay(10,
        ManagedPeripheralSupport.wakeDelay(mediaHz, cpuHz, aonHz)))
    ingress.rawClock := rawRxClock
    ingress.commonReset := commonReset
    ingress.payload := Cat(gmiiRxValid, gmiiRxError, gmiiRxData)
    ingress.active := gmiiRxValid
    ingress.quiesce := control(1).quiesce
    ingress.isolate := control(1).isolate
    rx.io.gmiiData := ingress.delayed(7, 0)
    rx.io.gmiiError := ingress.delayed(8)
    rx.io.gmiiValid := ingress.delayed(9)
    gmiiTxData := tx.io.gmiiData
    gmiiTxEnable := tx.io.gmiiEnable
    gmiiTxError := tx.io.gmiiError
    val receiverWake = ManagedPeripheralSupport.level(ingress.wake, sourceClock, cpuRelease.resetOut)
    withClockAndReset(sourceClock, cpuRelease.resetOut) {
        control(0).wake := RegNext(dirty || ((txQ || txIso) &&
            (streams.txData.valid || streams.txControl.valid)), false.B)
        control(1).wake := RegNext(dirty || receiverWake || !rxStop.settled, false.B)
    }
    val txDrainCpu = withClockAndReset(sourceClock, cpuRelease.resetOut) {
        RegNext(txQ && adapter.io.txIdle && txFifo.sourceIdle && txConfig.sourceIdle &&
            !dirty && txStats.destinationIdle, false.B)
    }
    val rxDrainCpu = withClockAndReset(sourceClock, cpuRelease.resetOut) {
        RegNext(rxQ && adapter.io.rxIdle && rxFifo.destinationIdle && rxConfig.sourceIdle &&
            !dirty && rxStats.destinationIdle && rxStop.settled, false.B)
    }
    val txDrain = ManagedPeripheralSupport.level(txDrainCpu, txManaged, txRelease.resetOut)
    val rxDrain = ManagedPeripheralSupport.level(rxDrainCpu, rxManaged, rxRelease.resetOut)
    localIdle(0) := txDrain && !tx.io.busy && txFifo.destinationIdle && txStats.sourceIdle &&
        !txConfig.destination.valid
    localIdle(1) := rxDrain && !rx.io.busy && rxFifo.sourceIdle && rxStats.sourceIdle &&
        !rxConfig.destination.valid && ingress.empty
    for ((domainClock, n) <- Seq(txManaged, rxManaged).zipWithIndex) {
        val agent = Module(new PeripheralQuiesceAck)
        agent.domainClock := domainClock
        agent.commonReset := commonReset
        agent.quiesce := control(n).quiesce
        agent.idle := localIdle(n)
        control(n).ack := agent.ack
    }
    port.linkUp := ManagedPeripheralSupport.level(linkUp, sourceClock, cpuRelease.resetOut)
    val previousLink = withClockAndReset(sourceClock, cpuRelease.resetOut) { RegNext(port.linkUp, false.B) }
    val configPending = dirty || !txConfig.sourceIdle || !rxConfig.sourceIdle
    val txBusyLevel = withClockAndReset(txManaged, txRelease.resetOut) { RegNext(tx.io.busy, false.B) }
    val rxBusyLevel = withClockAndReset(rxManaged, rxRelease.resetOut) { RegNext(!rxConfigurationIdle, false.B) }
    port.txBusy := ManagedPeripheralSupport.level(txBusyLevel, sourceClock, cpuRelease.resetOut) ||
        !adapter.io.txIdle || !txFifo.sourceIdle || configPending
    port.rxBusy := ManagedPeripheralSupport.level(rxBusyLevel, sourceClock, cpuRelease.resetOut) || configPending ||
        !rxStop.settled || (port.rxStopRequest.get && !rxStop.drained)
    val txDelta = Mux(txStats.delta.valid, txStats.delta.bits.asUInt, 0.U).asTypeOf(Vec(3, UInt(32.W)))
    val rxDelta = Mux(rxStats.delta.valid, rxStats.delta.bits.asUInt, 0.U).asTypeOf(Vec(4, UInt(32.W)))
    port.deltas.get := VecInit(Seq(txDelta(0), rxDelta(0), rxDelta(1), rxDelta(2), txDelta(2), rxDelta(3)))
    port.events := Cat(port.linkUp =/= previousLink, txDelta(1).orR, rxDelta(2).orR,
        rxDelta(1).orR, rxDelta(0).orR, txDelta(0).orR)
    port.txBytes := 0.U
    port.rxBytes := 0.U
    port.mdioIn := mdioIn
    mdc := port.mdc
    mdioOut := port.mdioOut
    mdioOe := port.mdioOe
    irq := csr.io.irq.orR
}
