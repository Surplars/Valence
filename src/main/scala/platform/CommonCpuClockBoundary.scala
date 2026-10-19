package soc.platform

import chisel3._
import chisel3.util._
import soc.ip.bus.{CdcLevel, CdcMailbox, CdcResetRelease, HeldResponseCdcDataFifo}
import soc.ip.tilelink.TileLinkClockDomainBoundary

/** Complete common tile boundary, always-clocked independent CPU/fabric domains.
  * Every protocol lane has independent Held-II1 storage. In particular D and
  * whole-LineGrant may both transfer on the same edge. Source/sink/native owner,
  * clear kind, maintenance epoch and MSI response ownership are never remapped.
  * Only common cold reset is supported and it must cover external owners too.
  * Empty reports describe transport only, never Home/DDR/DMA transaction drain.
  */
class CommonCpuClockBoundary(p: CommonCpuTilePortParams = CommonCpuTilePortParams(), depth: Int = 16)
    extends RawModule {
    require(depth >= 4 && isPow2(depth))
    val cpuClock = IO(Input(Clock()))
    val fabricClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val cpu = IO(Flipped(new CommonCpuTilePort(p)))
    val fabric = IO(new CommonCpuTilePort(p))
    val cpuLinkReady = IO(Output(Bool()))
    val fabricLinkReady = IO(Output(Bool()))
    val cpuTransportEmpty = IO(Output(Bool()))
    val fabricTransportEmpty = IO(Output(Bool()))
    val cpuEmptyInFabric = IO(Output(Bool()))
    val fabricEmptyInCpu = IO(Output(Bool()))
    private val cpuRelease = Module(new CdcResetRelease)
    cpuRelease.clockIn := cpuClock; cpuRelease.asyncReset := commonColdReset
    private val fabricRelease = Module(new CdcResetRelease)
    fabricRelease.clockIn := fabricClock; fabricRelease.asyncReset := commonColdReset
    private def level(value: Bool, inCpu: Boolean): Bool = {
        val crossing = Module(new CdcLevel)
        crossing.clockIn := (if (inCpu) cpuClock else fabricClock)
        crossing.resetIn := (if (inCpu) cpuRelease.resetOut else fabricRelease.resetOut)
        crossing.levelIn := value
        crossing.levelOut
    }
    cpuLinkReady := !cpuRelease.resetOut.asBool && level(!fabricRelease.resetOut.asBool, inCpu = true)
    fabricLinkReady := !fabricRelease.resetOut.asBool && level(!cpuRelease.resetOut.asBool, inCpu = false)
    private val empties = scala.collection.mutable.ArrayBuffer.empty[(Bool, Bool)]
    private def forward[T <: Data](input: DecoupledIO[T], output: DecoupledIO[T], toFabric: Boolean): Unit = {
        val fifo = Module(new HeldResponseCdcDataFifo(input.bits.getWidth, depth))
        fifo.sourceClock := (if (toFabric) cpuClock else fabricClock)
        fifo.destinationClock := (if (toFabric) fabricClock else cpuClock)
        fifo.commonReset := commonColdReset
        val sourceReady = if (toFabric) cpuLinkReady else fabricLinkReady
        val destinationReady = if (toFabric) fabricLinkReady else cpuLinkReady
        fifo.source.valid := input.valid && sourceReady
        fifo.source.bits := input.bits.asUInt
        input.ready := fifo.source.ready && sourceReady
        output.valid := fifo.destination.valid && destinationReady
        output.bits := fifo.destination.bits.asTypeOf(output.bits)
        fifo.destination.ready := output.ready && destinationReady
        empties += (if (toFabric) (fifo.sourceIdle, fifo.destinationIdle)
            else (fifo.destinationIdle, fifo.sourceIdle))
    }
    private def coherent(input: soc.bus.tilelink.TLBundle, output: soc.bus.tilelink.TLBundle,
        params: soc.bus.tilelink.TLParams): Unit = {
        val crossing = Module(new TileLinkClockDomainBoundary(params, depth, heldResponseStorage = true))
        crossing.cpuClock := cpuClock; crossing.fabricClock := fabricClock
        crossing.commonColdReset := commonColdReset
        crossing.cpu <> input; output <> crossing.fabric
        empties += ((crossing.cpuTransportEmpty, crossing.fabricTransportEmpty))
    }
    coherent(cpu.instructionFetch, fabric.instructionFetch, p.instruction)
    for (i <- 0 until p.coherentClients) {
        coherent(cpu.coherent(i), fabric.coherent(i), p.coherent)
        forward(fabric.lineGrant(i), cpu.lineGrant(i), toFabric = false)
    }
    for (i <- 0 until p.scalarPorts) {
        forward(cpu.scalar(i).request, fabric.scalar(i).request, toFabric = true)
        forward(fabric.scalar(i).response, cpu.scalar(i).response, toFabric = false)
    }
    forward(fabric.msi.request, cpu.msi.request, toFabric = false)
    forward(cpu.msi.response, fabric.msi.response, toFabric = true)
    forward(fabric.maintenance, cpu.maintenance, toFabric = false)
    forward(cpu.maintenanceStatus, fabric.maintenanceStatus, toFabric = true)
    forward(fabric.fabricDrainedEpoch, cpu.fabricDrainedEpoch, toFabric = false)
    cpu.timerInterrupt := level(fabric.timerInterrupt, inCpu = true)
    cpu.softwareInterrupt := level(fabric.softwareInterrupt, inCpu = true)

    // Periodic atomic time snapshots are intentionally excluded from transport
    // drain: they own no memory transaction and run continuously. No per-bit
    // synchronization of the changing 64-bit timer is permitted.
    private val time = Module(new CdcMailbox(64))
    time.sourceClock := fabricClock; time.destinationClock := cpuClock
    time.commonReset := commonColdReset
    time.source.valid := fabricLinkReady; time.source.bits := fabric.timeSnapshot
    time.destination.ready := cpuLinkReady
    cpu.timeSnapshot := withClockAndReset(cpuClock, cpuRelease.resetOut) {
        val snapshot = RegInit(0.U(64.W))
        when(time.destination.fire) { snapshot := time.destination.bits }
        snapshot
    }
    cpuTransportEmpty := cpuLinkReady && empties.map(_._1).reduce(_ && _)
    fabricTransportEmpty := fabricLinkReady && empties.map(_._2).reduce(_ && _)
    cpuEmptyInFabric := level(cpuTransportEmpty, inCpu = false)
    fabricEmptyInCpu := level(fabricTransportEmpty, inCpu = true)
}
