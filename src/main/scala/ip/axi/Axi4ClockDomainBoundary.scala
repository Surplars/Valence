package soc.ip.axi

import chisel3._
import chisel3.util._
import soc.ip.bus.{CdcLevel, CdcResetRelease, HeldResponseCdcDataFifo}

/** Complete AXI4 transport between variable fabric and fixed DDR UI clocks.
  * AW, W and AR have separate forward storage; B and R have separate return
  * storage. AW and W remain independent, including W-before-AW. Every payload
  * field, ID, LAST and response code is preserved without remapping or joining.
  *
  * Common cold reset must cover BOTH endpoints and their transaction owners.
  * No one-sided reset, hot reset, clock gating or runtime frequency permission
  * is provided here. A locally empty FIFO may still have a remote held beat;
  * even both transport-empty observations do NOT prove outstanding AXI owners
  * drained (e.g. an accepted AR awaiting its first R). The caller must quiesce
  * producers, drain real owners and synchronize observations before clock stop.
  * Physical Gray-bus max-delay/bus-skew and reset/clock CDC signoff are required.
  */
class Axi4ClockDomainBoundary(addressWidth: Int = 32, idWidth: Int = 4, depth: Int = 16)
    extends RawModule {
    require(depth >= 4 && isPow2(depth))
    val fabricClock = IO(Input(Clock()))
    val ddrClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val fabric = IO(Flipped(new Axi4MemoryPort(addressWidth, idWidth)))
    val ddr = IO(new Axi4MemoryPort(addressWidth, idWidth))
    val fabricLinkReady = IO(Output(Bool()))
    val ddrLinkReady = IO(Output(Bool()))
    val fabricTransportEmpty = IO(Output(Bool()))
    val ddrTransportEmpty = IO(Output(Bool()))

    private val fabricRelease = Module(new CdcResetRelease)
    fabricRelease.clockIn := fabricClock; fabricRelease.asyncReset := commonColdReset
    private val ddrRelease = Module(new CdcResetRelease)
    ddrRelease.clockIn := ddrClock; ddrRelease.asyncReset := commonColdReset
    private def synchronize(value: Bool, toDdr: Boolean): Bool = {
        val sync = Module(new CdcLevel)
        sync.clockIn := (if (toDdr) ddrClock else fabricClock)
        sync.resetIn := (if (toDdr) ddrRelease.resetOut else fabricRelease.resetOut)
        sync.levelIn := value
        sync.levelOut
    }
    fabricLinkReady := !fabricRelease.resetOut.asBool && synchronize(!ddrRelease.resetOut.asBool, false)
    ddrLinkReady := !ddrRelease.resetOut.asBool && synchronize(!fabricRelease.resetOut.asBool, true)

    private def forward[T <: Data](input: DecoupledIO[T], output: DecoupledIO[T],
        toDdr: Boolean): (Bool, Bool) = {
        val fifo = Module(new HeldResponseCdcDataFifo(input.bits.getWidth, depth))
        fifo.sourceClock := (if (toDdr) fabricClock else ddrClock)
        fifo.destinationClock := (if (toDdr) ddrClock else fabricClock)
        fifo.commonReset := commonColdReset
        val sourceReady = if (toDdr) fabricLinkReady else ddrLinkReady
        val destinationReady = if (toDdr) ddrLinkReady else fabricLinkReady
        fifo.source.valid := input.valid && sourceReady
        fifo.source.bits := input.bits.asUInt
        input.ready := fifo.source.ready && sourceReady
        output.valid := fifo.destination.valid && destinationReady
        output.bits := fifo.destination.bits.asTypeOf(output.bits)
        fifo.destination.ready := output.ready && destinationReady
        if (toDdr) (fifo.sourceIdle, fifo.destinationIdle) else (fifo.destinationIdle, fifo.sourceIdle)
    }
    private val empty = Seq(
        forward(fabric.aw, ddr.aw, true), forward(fabric.w, ddr.w, true),
        forward(ddr.b, fabric.b, false), forward(fabric.ar, ddr.ar, true),
        forward(ddr.r, fabric.r, false))
    fabricTransportEmpty := fabricLinkReady && empty.map(_._1).reduce(_ && _)
    ddrTransportEmpty := ddrLinkReady && empty.map(_._2).reduce(_ && _)
}
