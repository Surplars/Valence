package soc.ip.ethernet

import chisel3._
import chisel3.util._
import soc.ip.bus._

/** Native data/keep/last/bad form one inseparable CDC payload. RAM slots plus
  * destination output/prefetch must all be drained before either clock stops.
  * Reset is coordinated with DMA and both frame engines, not hot MAC reset.
  */
class EthernetFrameClockBridge(depth: Int = 16) extends RawModule {
    val sourceClock = IO(Input(Clock()))
    val destinationClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val source = IO(Flipped(Decoupled(new EthernetFrameBeat(4))))
    val destination = IO(Decoupled(new EthernetFrameBeat(4)))
    val sourceIdle = IO(Output(Bool()))
    val destinationIdle = IO(Output(Bool()))
    val fifo = Module(new CdcDataFifo(38, depth))
    fifo.sourceClock := sourceClock
    fifo.destinationClock := destinationClock
    fifo.commonReset := commonReset
    fifo.source.valid := source.valid
    fifo.source.bits := source.bits.asUInt
    source.ready := fifo.source.ready
    destination.valid := fifo.destination.valid
    destination.bits := fifo.destination.bits.asTypeOf(new EthernetFrameBeat(4))
    fifo.destination.ready := destination.ready
    sourceIdle := fifo.sourceIdle
    destinationIdle := fifo.destinationIdle
}

/** Atomic config image: wire MAC address, TX/RX enable, promiscuous/broadcast.
  * The receiving frame engine applies snapshots only at a safe frame boundary.
  * Committing in one media domain is NOT evidence the other domain committed.
  */
class EthernetConfigSnapshot extends Bundle {
    val macAddress = UInt(48.W)
    val txEnable = Bool()
    val rxEnable = Bool()
    val promiscuous = Bool()
    val broadcastEnable = Bool()
}

class EthernetConfigClockBridge extends RawModule {
    val sourceClock = IO(Input(Clock()))
    val destinationClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val source = IO(Flipped(Decoupled(new EthernetConfigSnapshot)))
    val destination = IO(Decoupled(new EthernetConfigSnapshot))
    val sourceIdle = IO(Output(Bool()))
    val mailbox = Module(new CdcMailbox(52))
    mailbox.sourceClock := sourceClock
    mailbox.destinationClock := destinationClock
    mailbox.commonReset := commonReset
    mailbox.source.valid := source.valid
    mailbox.source.bits := source.bits.asUInt
    source.ready := mailbox.source.ready
    destination.valid := mailbox.destination.valid
    destination.bits := mailbox.destination.bits.asTypeOf(new EthernetConfigSnapshot)
    mailbox.destination.ready := destination.ready
    sourceIdle := mailbox.sourceIdle
}
