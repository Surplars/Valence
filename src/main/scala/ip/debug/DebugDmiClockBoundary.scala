package soc.ip.debug

import chisel3._
import soc.ip.bus.{CdcMailbox, CdcResetRelease}

/** Complete DMI request/response crossing, preserving payload and backpressure.
  * Link loss cancels only the DMI transport epoch, not accepted RAM transactions
  * in the loader. Both mailbox endpoints reset together on link loss; local
  * synchronous release prevents stale requests/responses replaying on reconnect.
  * Never use the link reset to reset the fabric or a memory transaction owner.
  */
class DebugDmiClockBoundary(addressBits: Int = 7) extends RawModule {
    val sourceClock = IO(Input(Clock()))
    val destinationClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val source = IO(Flipped(new DebugDmiPort(addressBits)))
    val destination = IO(new DebugDmiPort(addressBits))
    val sourceLinkUp = IO(Input(Bool()))
    val destinationLinkUp = IO(Output(Bool()))
    private val transportReset = (commonColdReset.asBool || !sourceLinkUp).asAsyncReset
    val release = Module(new CdcResetRelease)
    release.clockIn := destinationClock
    release.asyncReset := transportReset
    destinationLinkUp := !release.resetOut.asBool
    val requests = Module(new CdcMailbox((new DmiRequest(addressBits)).getWidth))
    requests.sourceClock := sourceClock
    requests.destinationClock := destinationClock
    requests.commonReset := transportReset
    requests.source.valid := source.request.valid
    requests.source.bits := source.request.bits.asUInt
    source.request.ready := requests.source.ready
    destination.request.valid := requests.destination.valid
    destination.request.bits := requests.destination.bits.asTypeOf(destination.request.bits)
    requests.destination.ready := destination.request.ready
    val responses = Module(new CdcMailbox((new DmiResponse).getWidth))
    responses.sourceClock := destinationClock
    responses.destinationClock := sourceClock
    responses.commonReset := transportReset
    responses.source.valid := destination.response.valid
    responses.source.bits := destination.response.bits.asUInt
    destination.response.ready := responses.source.ready
    source.response.valid := responses.destination.valid
    source.response.bits := responses.destination.bits.asTypeOf(source.response.bits)
    responses.destination.ready := source.response.ready
}
