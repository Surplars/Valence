package soc.ip.tilelink

import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.ip.bus.{CdcDataFifo, CdcLevel, CdcResetRelease, HeldResponseCdcDataFifo}

/** Opt-in CPU/fabric transport boundary. Existing SoC clock profiles are unchanged.
  *
  * Each complete A/B/C/D/E beat has its own asynchronous FIFO. Source and sink
  * identifiers, multibeat messages, denied/corrupt and masks are transported
  * unchanged; transaction ownership stays in the cache and Home. In particular,
  * there is no shared request token limiting the boundary to one outstanding
  * request, and a blocked A or D channel cannot block B, C or E storage.
  *
  * Both clocks must remain running. Only a common cold reset is supported: it
  * starts a new epoch in BOTH endpoints and may discard old-epoch transport.
  * The system must reset all affected transaction owners as well (or first
  * drain them); resetting this FIFO cannot cancel an accepted external write.
  * This component neither authorizes hot reset nor gates either clock. Before
  * any future retention/gating operation, the caller must stop NEW CPU work,
  * drain all cache/Home/DDR owners while these channels continue to progress,
  * then prove BOTH endpoint transport-empty indications. Queue empty alone is
  * not transaction drained: a Home can owe D, a cache can owe C/E, or an uncached
  * operation can still be pending outside this component.
  *
  * The compatibility FIFO has a synchronous RAM read/capture stage (at most one
  * output beat every two destination clocks). heldResponseStorage selects the
  * independently qualified held-response pipeline, capable of one output beat
  * per destination clock when supplied and not backpressured. It keeps a stalled
  * RAM response owned until capture; no transaction credits are removed.
  * Physical Gray-bus max-delay/bus-skew constraints and clock/reset
  * CDC qualification are required for each board profile; digital tests cannot
  * qualify those properties. No clock ratio or frequency is assumed here.
  */
class TileLinkClockDomainBoundary(params: TLParams, depth: Int = 4,
    heldResponseStorage: Boolean = false) extends RawModule {
    require(depth >= 4 && isPow2(depth), "independent channel capacity must be a power of two >= 4")
    val cpuClock = IO(Input(Clock()))
    val fabricClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val cpu = IO(Flipped(new TLBundle(params)))
    val fabric = IO(new TLBundle(params))

    // These are LOCAL-domain observations, not synchronized global drain ACKs.
    // A FIFO's sourceIdle can be true while its remote held output is occupied.
    val cpuTransportEmpty = IO(Output(Bool()))
    val fabricTransportEmpty = IO(Output(Bool()))
    val cpuLinkReady = IO(Output(Bool()))
    val fabricLinkReady = IO(Output(Bool()))

    private val cpuRelease = Module(new CdcResetRelease)
    cpuRelease.clockIn := cpuClock
    cpuRelease.asyncReset := commonColdReset
    private val fabricRelease = Module(new CdcResetRelease)
    fabricRelease.clockIn := fabricClock
    fabricRelease.asyncReset := commonColdReset
    private val fabricReleasedInCpu = Module(new CdcLevel)
    fabricReleasedInCpu.clockIn := cpuClock
    fabricReleasedInCpu.resetIn := cpuRelease.resetOut
    fabricReleasedInCpu.levelIn := !fabricRelease.resetOut.asBool
    private val cpuReleasedInFabric = Module(new CdcLevel)
    cpuReleasedInFabric.clockIn := fabricClock
    cpuReleasedInFabric.resetIn := fabricRelease.resetOut
    cpuReleasedInFabric.levelIn := !cpuRelease.resetOut.asBool
    cpuLinkReady := !cpuRelease.resetOut.asBool && fabricReleasedInCpu.levelOut
    fabricLinkReady := !fabricRelease.resetOut.asBool && cpuReleasedInFabric.levelOut

    private def forward[T <: Data](input: DecoupledIO[T], output: DecoupledIO[T],
        toFabric: Boolean): (Bool, Bool) = {
        def connect(source: DecoupledIO[UInt], destination: DecoupledIO[UInt],
            sourceIdle: Bool, destinationIdle: Bool): (Bool, Bool) = {
            val sourceReady = if (toFabric) cpuLinkReady else fabricLinkReady
            val destinationReady = if (toFabric) fabricLinkReady else cpuLinkReady
            source.valid := input.valid && sourceReady
            source.bits := input.bits.asUInt
            input.ready := source.ready && sourceReady
            output.valid := destination.valid && destinationReady
            output.bits := destination.bits.asTypeOf(output.bits)
            destination.ready := output.ready && destinationReady
            if (toFabric) (sourceIdle, destinationIdle) else (destinationIdle, sourceIdle)
        }
        if (heldResponseStorage) {
            val fifo = Module(new HeldResponseCdcDataFifo(input.bits.getWidth, depth))
            fifo.sourceClock := (if (toFabric) cpuClock else fabricClock)
            fifo.destinationClock := (if (toFabric) fabricClock else cpuClock)
            fifo.commonReset := commonColdReset
            connect(fifo.source, fifo.destination, fifo.sourceIdle, fifo.destinationIdle)
        } else {
            val fifo = Module(new CdcDataFifo(input.bits.getWidth, depth))
            fifo.sourceClock := (if (toFabric) cpuClock else fabricClock)
            fifo.destinationClock := (if (toFabric) fabricClock else cpuClock)
            fifo.commonReset := commonColdReset
            connect(fifo.source, fifo.destination, fifo.sourceIdle, fifo.destinationIdle)
        }
    }

    private val empty = Seq(
        forward(cpu.a, fabric.a, toFabric = true),
        forward(fabric.b, cpu.b, toFabric = false),
        forward(cpu.c, fabric.c, toFabric = true),
        forward(fabric.d, cpu.d, toFabric = false),
        forward(cpu.e, fabric.e, toFabric = true)
    )
    cpuTransportEmpty := cpuLinkReady && empty.map(_._1).reduce(_ && _)
    fabricTransportEmpty := fabricLinkReady && empty.map(_._2).reduce(_ && _)
}
