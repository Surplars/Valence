package soc.platform

import chisel3._
import chisel3.util._
import soc.core.inorder._

/** Full-capacity I1 CPU-domain tile. Common AIA, memory map and boot image are
  * outside the CPU choice. Dirty FENCE.I writes reach the shared Home and actual
  * DDR responses before the original core invalidates fetch state and retires.
  */
class CommonI1CpuTile(p: FiveStageConfig = CommonCpuProfile.I1.i1,
    boundary: CommonCpuTilePortParams = CommonCpuTilePortParams()) extends Module {
    require(p.xlen == 64 && p.withAia && p.externalFenceICompletion && p.coherentLineGrants)
    require(p.instructionCacheBytes == 32768 && p.dataCacheBytes == 32768 && p.coherentCacheWays == 2)
    require(p.tlbEntries >= 16 && p.bankedTlbProofs && p.indexedDataProofs)
    val io = IO(new Bundle {
        val bus = new CommonCpuTilePort(boundary)
        val retire = Valid(new FiveStageRetire(p))
        val trapTaken = Output(Bool())
        val trapPc = Output(UInt(64.W))
        val trapCause = Output(UInt(64.W))
        val cycles = Output(UInt(64.W))
        val instructions = Output(UInt(64.W))
        val maintenancePending = Output(Bool())
    })
    val tile = Module(new FiveStageCachedCore(p, externalDataInvalidate = true,
        acknowledgedDataInvalidate = true))
    for (port <- Seq(tile.io.instructionMemory, tile.io.dataMemory)) {
        port.request.ready := false.B
        port.response.valid := false.B
        port.response.bits := 0.U.asTypeOf(port.response.bits)
        assert(!port.request.valid, "coherent I1 tile unexpectedly used legacy burst backend")
    }
    for (i <- 0 until 2) {
        io.bus.coherent(i) <> tile.io.coherent.get(i)
        tile.io.lineGrants.get(i) <> io.bus.lineGrant(i)
    }
    io.bus.instructionFetch.a.valid := false.B
    io.bus.instructionFetch.a.bits := 0.U.asTypeOf(io.bus.instructionFetch.a.bits)
    io.bus.instructionFetch.b.ready := false.B
    io.bus.instructionFetch.c.valid := false.B
    io.bus.instructionFetch.c.bits := 0.U.asTypeOf(io.bus.instructionFetch.c.bits)
    io.bus.instructionFetch.d.ready := false.B
    io.bus.instructionFetch.e.valid := false.B
    io.bus.instructionFetch.e.bits := 0.U.asTypeOf(io.bus.instructionFetch.e.bits)
    assert(!io.bus.instructionFetch.b.valid && !io.bus.instructionFetch.d.valid,
        "fabric addressed an inactive I1 noncoherent fetch port")
    val lanes = (0 until 2).map { i =>
        val lane = Module(new CommonNativeOwnerAdapter(boundary, carriesClear = i == 1))
        lane.io.native <> tile.io.uncached.get(i)
        lane.io.needsCoherenceLookup := true.B
        lane.io.clearReservation := (if (i == 1) tile.io.clearCoherentReservation.get else false.B)
        io.bus.scalar(i) <> lane.io.transport
        lane
    }
    tile.io.time := io.bus.timeSnapshot
    tile.io.timerIrq := io.bus.timerInterrupt
    tile.io.softwareIrq := io.bus.softwareInterrupt
    tile.io.externalIrq := false.B
    tile.io.supervisorExternalIrq.get := false.B
    tile.io.msi.get <> io.bus.msi
    tile.io.invalidateReservation.get := false.B

    val request = tile.io.fenceIFlush.get
    val epoch = RegInit(0.U(boundary.maintenanceEpochBits.W))
    val active = RegInit(false.B)
    val flushIssued = RegInit(false.B)
    val flushDone = RegInit(false.B)
    val sent = RegInit(false.B)
    val acknowledged = RegInit(false.B)
    when(request && !active) { active := true.B; epoch := epoch + 1.U }
    when(!request) {
        active := false.B; flushIssued := false.B; flushDone := false.B
        sent := false.B; acknowledged := false.B
    }
    // A single pulse starts a sticky cache flush; holding invalidate high would
    // manufacture endless reservation-clear events and prevent genuine drain.
    val startFlush = request && active && tile.io.fenceIFetchDrained.get && !flushIssued
    tile.io.invalidateData.get := startFlush
    when(startFlush) { flushIssued := true.B }
    when(flushIssued && tile.io.invalidateDataDone.get) { flushDone := true.B }
    val nativeIdle = lanes.map(_.io.idle).reduce(_ && _)
    io.bus.maintenanceStatus.valid := request && active && flushDone && nativeIdle &&
        tile.io.fenceIFetchDrained.get && !sent
    io.bus.maintenanceStatus.bits.epoch := epoch
    io.bus.maintenanceStatus.bits.privateOwnersDrained := nativeIdle
    io.bus.maintenanceStatus.bits.dirtyWritebackCompleted := flushDone
    io.bus.maintenanceStatus.bits.fetchQuiescent := tile.io.fenceIFetchDrained.get
    io.bus.maintenanceStatus.bits.invalidationsCompleted := false.B
    when(io.bus.maintenanceStatus.fire) { sent := true.B }
    io.bus.fabricDrainedEpoch.ready := sent && !acknowledged
    when(io.bus.fabricDrainedEpoch.fire) {
        assert(io.bus.fabricDrainedEpoch.bits === epoch, "I1 accepted a stale Home drain epoch")
        acknowledged := true.B
    }
    tile.io.fenceIFlushReady.get := request && flushDone && acknowledged
    io.bus.maintenance.ready := false.B // external download halt requires its own precise boundary
    io.maintenancePending := request
    io.retire := tile.io.retire
    io.trapTaken := tile.io.trapTaken; io.trapPc := tile.io.trapPc; io.trapCause := tile.io.trapCause
    io.cycles := tile.io.cycles; io.instructions := tile.io.instructions
}
