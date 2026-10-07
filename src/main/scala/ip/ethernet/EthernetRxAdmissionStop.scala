package soc.ip.ethernet

import chisel3._
import soc.ip.bus._

/** Busy-safe producer barrier, not a reset or a clock gate.
  *
  * A stop offer closes admission before waiting for native frame/output and
  * source FIFO ownership to drain. Only then is the command acknowledged.
  * The source also checks destination FIFO/prefetch and adapter status storage.
  * DMA memory writes are outside this barrier and must drain separately.
  * Desired levels may coalesce, but a sent release cannot reuse an old stop
  * acknowledgement: dirty and mailbox ownership qualify every drained result.
  */
class EthernetRxAdmissionStop extends RawModule {
    val sourceClock = IO(Input(Clock()))
    val destinationClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val requested = IO(Input(Bool()))
    val sourceDrained = IO(Input(Bool()))
    val destinationFrameIdle = IO(Input(Bool()))
    val destinationFifoIdle = IO(Input(Bool()))
    val stopNewFrames = IO(Output(Bool()))
    val settled = IO(Output(Bool()))
    val drained = IO(Output(Bool()))

    val sourceRelease = Module(new CdcResetRelease)
    sourceRelease.clockIn := sourceClock
    sourceRelease.asyncReset := commonReset
    val destinationRelease = Module(new CdcResetRelease)
    destinationRelease.clockIn := destinationClock
    destinationRelease.asyncReset := commonReset
    val command = Module(new CdcMailbox(1))
    command.sourceClock := sourceClock
    command.destinationClock := destinationClock
    command.commonReset := commonReset
    val sent = withClockAndReset(sourceClock, sourceRelease.resetOut) { RegInit(false.B) }
    val dirty = requested =/= sent
    command.source.valid := dirty
    command.source.bits := requested.asUInt
    withClockAndReset(sourceClock, sourceRelease.resetOut) {
        when(command.source.fire) { sent := requested }
    }
    val stopped = withClockAndReset(destinationClock, destinationRelease.resetOut) { RegInit(false.B) }
    stopNewFrames := stopped || (command.destination.valid && command.destination.bits(0))
    command.destination.ready := !command.destination.valid || !command.destination.bits(0) ||
        (destinationFrameIdle && destinationFifoIdle)
    withClockAndReset(destinationClock, destinationRelease.resetOut) {
        when(command.destination.fire) { stopped := command.destination.bits(0) }
        when(command.destination.fire && command.destination.bits(0)) {
            assert(destinationFrameIdle && destinationFifoIdle,
                "RX stop acknowledgement cannot precede native frame and FIFO drain")
        }
    }
    settled := !dirty && command.sourceIdle
    drained := requested && settled && sourceDrained
}
