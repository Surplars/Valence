package ip

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.bus._
import soc.ip.ethernet._

/** CDC/clock-policy only: no CPU, frame engine, PHY or vendor MAC. */
class SelfGmacCdcTop extends RawModule {
    val controlClock = IO(Input(Clock()))
    val txClock = IO(Input(Clock()))
    val rxClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val txIn = IO(Flipped(Decoupled(new EthernetFrameBeat(4))))
    val txOut = IO(Decoupled(new EthernetFrameBeat(4)))
    val rxIn = IO(Flipped(Decoupled(new EthernetFrameBeat(4))))
    val rxOut = IO(Decoupled(new EthernetFrameBeat(4)))
    val configIn = IO(Flipped(Decoupled(new EthernetConfigSnapshot)))
    val configTx = IO(Decoupled(new EthernetConfigSnapshot))
    val configRx = IO(Decoupled(new EthernetConfigSnapshot))
    val txIncrement = IO(Input(UInt(16.W)))
    val rxIncrement = IO(Input(UInt(16.W)))
    val txDelta = IO(Decoupled(UInt(16.W)))
    val rxDelta = IO(Decoupled(UInt(16.W)))
    val stopRequest = IO(Input(Bool()))
    val wake = IO(Input(Bool()))
    val clearFault = IO(Input(Bool()))
    val localIdle = IO(Input(Bool()))
    val quiesce = IO(Output(Bool()))
    val stopAdmission = IO(Output(Bool()))
    val clockEnable = IO(Output(Bool()))
    val isolate = IO(Output(Bool()))
    val allowAdmission = IO(Output(Bool()))
    val stopped = IO(Output(Bool()))
    val fault = IO(Output(Bool()))
    val txSourceIdle = IO(Output(Bool()))
    val txDestinationIdle = IO(Output(Bool()))
    val txFifo = Module(new EthernetFrameClockBridge(16))
    txFifo.sourceClock := controlClock
    txFifo.destinationClock := txClock
    txFifo.commonReset := commonReset
    txFifo.source <> txIn
    txOut <> txFifo.destination
    txSourceIdle := txFifo.sourceIdle
    txDestinationIdle := txFifo.destinationIdle
    val rxFifo = Module(new EthernetFrameClockBridge(16))
    rxFifo.sourceClock := rxClock
    rxFifo.destinationClock := controlClock
    rxFifo.commonReset := commonReset
    rxFifo.source <> rxIn
    rxOut <> rxFifo.destination
    val txConfig = Module(new EthernetConfigClockBridge)
    val rxConfig = Module(new EthernetConfigClockBridge)
    txConfig.sourceClock := controlClock
    txConfig.destinationClock := txClock
    txConfig.commonReset := commonReset
    rxConfig.sourceClock := controlClock
    rxConfig.destinationClock := rxClock
    rxConfig.commonReset := commonReset
    // Atomic broadcast admission: neither branch may enqueue an image alone.
    configIn.ready := txConfig.source.ready && rxConfig.source.ready
    txConfig.source.valid := configIn.valid && rxConfig.source.ready
    rxConfig.source.valid := configIn.valid && txConfig.source.ready
    txConfig.source.bits := configIn.bits
    rxConfig.source.bits := configIn.bits
    configTx <> txConfig.destination
    configRx <> rxConfig.destination
    val txEvents = Module(new CdcAccumulator(16))
    txEvents.sourceClock := txClock
    txEvents.destinationClock := controlClock
    txEvents.commonReset := commonReset
    txEvents.increment := txIncrement
    txDelta <> txEvents.delta
    val rxEvents = Module(new CdcAccumulator(16))
    rxEvents.sourceClock := rxClock
    rxEvents.destinationClock := controlClock
    rxEvents.commonReset := commonReset
    rxEvents.increment := rxIncrement
    rxDelta <> rxEvents.delta
    val policy = withClockAndReset(controlClock, commonReset) { Module(new PeripheralClockControl(128, 3)) }
    policy.io.stopRequest := stopRequest
    policy.io.wake := wake
    policy.io.clearFault := clearFault
    val agent = Module(new PeripheralQuiesceAck)
    agent.domainClock := txClock
    agent.commonReset := commonReset
    agent.quiesce := policy.io.quiesce
    agent.idle := localIdle && txFifo.destinationIdle
    policy.io.domainAck := agent.ack
    quiesce := policy.io.quiesce
    stopAdmission := agent.stopAdmission
    clockEnable := policy.io.clockEnable
    isolate := policy.io.isolate
    allowAdmission := policy.io.allowAdmission
    stopped := policy.io.stopped
    fault := policy.io.fault
}

object SelfGmacCdcMain extends App {
    ChiselStage.emitSystemVerilogFile(new SelfGmacCdcTop, Array("--target-dir", args.head),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization"))
}
