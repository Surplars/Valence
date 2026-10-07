package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.bus._

/** CDC-only top for the explicitly authorized short xsim check. */
class ClockDomainCdcTop extends RawModule {
    val sourceClock = IO(Input(Clock()))
    val destinationClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val source = IO(Flipped(new RegisterPort))
    val destination = IO(new RegisterPort)
    val streamIn = IO(Flipped(Decoupled(new CdcStreamBeat)))
    val streamOut = IO(Decoupled(new CdcStreamBeat))
    val irqIn = IO(Input(Bool()))
    val irqOut = IO(Output(Bool()))
    val bridge = Module(new RegisterClockDomainBridge)
    bridge.sourceClock := sourceClock
    bridge.destinationClock := destinationClock
    bridge.commonReset := commonReset
    bridge.source <> source
    destination <> bridge.destination
    val fifo = Module(new StreamClockDomainFifo(16))
    fifo.sourceClock := sourceClock
    fifo.destinationClock := destinationClock
    fifo.commonReset := commonReset
    fifo.source <> streamIn
    streamOut <> fifo.destination
    val irq = Module(new CdcLevel)
    irq.clockIn := sourceClock
    irq.resetIn := bridge.sourceReset
    irq.levelIn := irqIn
    irqOut := irq.levelOut
}

object ClockDomainCdcMain extends App {
    ChiselStage.emitSystemVerilogFile(new ClockDomainCdcTop,
        Array("--target-dir", args.head), Array("--split-verilog"))
}
