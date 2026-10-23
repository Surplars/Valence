package soc.platform

import chisel3._
import chisel3.util._
import soc.core.inorder._

/** Full-capacity I1 CPU-domain tile. Common AIA, memory map and boot image are
  * outside the CPU choice. Dirty FENCE.I writes reach the shared Home and actual
  * DDR responses before the original core invalidates fetch state and retires.
  */
class CommonI1CpuTile(p: FiveStageConfig = CommonCpuProfile.I1.i1,
    boundary: CommonCpuTilePortParams = CommonCpuTilePortParams(),
    externalQuiesce: Boolean = false) extends Module {
    require(p.xlen == 64 && p.withAia && p.externalFenceICompletion && p.coherentLineGrants)
    require(p.instructionCacheBytes == 32768 && p.dataCacheBytes == 32768 && p.coherentCacheWays == 2)
    require(p.tlbEntries >= 16 && p.bankedTlbProofs && p.indexedDataProofs)
    val io = IO(new Bundle {
        // Architectural stop only. Coherent probes/responses remain live; this
        // status is deliberately not connected to a complete CMU drain ACK.
        val quiesceRequest = if (externalQuiesce) Some(Input(Bool())) else None
        val architecturalStopped = if (externalQuiesce) Some(Output(Bool())) else None
        // Local epoch readiness only; not an AON clock-gating permission.
        val runtimeHeld = if (boundary.runtimeMaintenance) Some(Valid(UInt(boundary.maintenanceEpochBits.W))) else None
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
        acknowledgedDataInvalidate = true, externalQuiesce = externalQuiesce || boundary.runtimeMaintenance,
        runtimeMaintenance = boundary.runtimeMaintenance))
    val runtimeStop = if (boundary.runtimeMaintenance) Some(WireDefault(false.B)) else None
    tile.io.quiesceRequest.foreach(_ := io.quiesceRequest.getOrElse(false.B) || runtimeStop.getOrElse(false.B))
    io.architecturalStopped.foreach(_ := tile.io.architecturalStopped.get)
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
    when(io.bus.maintenanceStatus.fire && (if (boundary.runtimeMaintenance) request else true.B)) { sent := true.B }
    io.bus.fabricDrainedEpoch.ready := sent && !acknowledged
    when(io.bus.fabricDrainedEpoch.fire && (if (boundary.runtimeMaintenance) request else true.B)) {
        assert(io.bus.fabricDrainedEpoch.bits === epoch, "I1 accepted a stale Home drain epoch")
        acknowledged := true.B
    }
    tile.io.fenceIFlushReady.get := request && flushDone && acknowledged
    if (boundary.runtimeMaintenance) {
        val runtimeActive = RegInit(false.B)
        val releasePending = if (boundary.runtimeCancellation) Some(RegInit(false.B)) else None
        val runtimeEpoch = Reg(UInt(boundary.maintenanceEpochBits.W))
        val runtimeFlushIssued = RegInit(false.B)
        val runtimeFlushDone = RegInit(0.U(2.W))
        val runtimeOffer = RegInit(false.B)
        val runtimeSent = RegInit(false.B)
        val runtimeAcknowledged = RegInit(false.B)
        val lastEpoch = Reg(UInt(boundary.maintenanceEpochBits.W))
        val lastValid = RegInit(false.B)
        val command = io.bus.maintenance
        command.ready := !runtimeActive && !releasePending.getOrElse(false.B) && !request && !active &&
            !(lastValid && command.bits.epoch === lastEpoch)
        when(command.fire) {
            assert(!command.bits.invalidateInstructions && !command.bits.invalidateTranslations,
                "runtime rate halt does not implement architectural invalidation commands")
            runtimeActive := true.B
            runtimeEpoch := command.bits.epoch
            lastEpoch := command.bits.epoch; lastValid := true.B
            runtimeFlushIssued := false.B; runtimeFlushDone := 0.U
            runtimeOffer := false.B; runtimeSent := false.B; runtimeAcknowledged := false.B
        }
        runtimeStop.get := runtimeActive
        val stopped = tile.io.architecturalStopped.get
        val privateIdle = tile.io.privateCachesQuiescent.get && nativeIdle
        val flushPulse = runtimeActive && stopped && !runtimeFlushIssued
        tile.io.runtimeFlush.get := flushPulse
        when(flushPulse) { runtimeFlushIssued := true.B }
        when(runtimeActive && runtimeFlushIssued) {
            runtimeFlushDone := runtimeFlushDone | tile.io.runtimeFlushDone.get
        }
        val privateDrained = runtimeActive && stopped && runtimeFlushDone.andR && privateIdle
        // Capture one drain observation into a held message. Later accepted
        // probes stay live and remain covered by fabric's true obligation counts.
        when(privateDrained) { runtimeOffer := true.B }
        // An older FENCE.I drains normally before architecturalStopped can rise.
        // Runtime status is offered only afterward, never replacing an older epoch.
        when(runtimeActive && stopped) {
            io.bus.maintenanceStatus.valid := runtimeOffer && !runtimeSent
            io.bus.maintenanceStatus.bits.epoch := runtimeEpoch
            io.bus.maintenanceStatus.bits.privateOwnersDrained := true.B
            io.bus.maintenanceStatus.bits.dirtyWritebackCompleted := runtimeFlushDone.andR
            io.bus.maintenanceStatus.bits.fetchQuiescent := stopped
            io.bus.maintenanceStatus.bits.invalidationsCompleted := false.B
            io.bus.fabricDrainedEpoch.ready := runtimeSent && !runtimeAcknowledged &&
                io.bus.fabricDrainedEpoch.bits === runtimeEpoch
        }
        io.bus.maintenanceStatus.bits.holdUntilResume.get := runtimeActive && stopped
        when(runtimeActive && stopped && io.bus.maintenanceStatus.fire) { runtimeSent := true.B }
        when(runtimeActive && stopped && io.bus.fabricDrainedEpoch.fire) {
            runtimeAcknowledged := true.B
        }
        val resume = io.bus.maintenanceResume.get
        // Cancellation-capable fabric keeps Home closed until maintenanceResumed,
        // not merely until this transport beat is consumed. Retain one matching
        // resume token locally so live cache/translation drain cannot feed back
        // through FIFO ready. Only actual release below may lower runtimeStop.
        // This adds one CPU edge to management release, not to normal requests.
        val applyResume = if (boundary.runtimeCancellation) {
            val resumePending = RegInit(false.B)
            resume.ready := runtimeActive && runtimeAcknowledged && !resumePending &&
                resume.bits === runtimeEpoch
            when(resume.fire) { resumePending := true.B }
            val apply = resumePending && privateDrained && runtimeAcknowledged
            when(apply) { resumePending := false.B }
            when(resumePending) {
                assert(runtimeActive && runtimeAcknowledged,
                    "pending runtime resume lost its active acknowledged epoch")
            }
            apply
        } else {
            resume.ready := privateDrained && runtimeAcknowledged && resume.bits === runtimeEpoch
            resume.fire
        }
        when(applyResume) {
            runtimeActive := false.B
            runtimeFlushIssued := false.B; runtimeFlushDone := 0.U
            runtimeOffer := false.B; runtimeSent := false.B; runtimeAcknowledged := false.B
        }
        if (boundary.runtimeCancellation) {
            val releaseEdges = RegInit(0.U(2.W))
            val released = RegInit(false.B)
            val response = io.bus.maintenanceResumed.get
            response.valid := releasePending.get && released
            response.bits := runtimeEpoch
            when(applyResume) {
                releasePending.get := true.B
                releaseEdges := 0.U
                released := false.B
            }
            // A falling stopped flag is combinational, not CPU progress proof.
            // Wait two real local edges after the aggregate request falls: the
            // first executes the core's release bubble, the second follows it.
            when(releasePending.get && !released) {
                when(tile.io.quiesceRequest.get) { releaseEdges := 0.U }
                    .otherwise {
                        when(releaseEdges === 1.U) { released := true.B }
                            .otherwise { releaseEdges := releaseEdges + 1.U }
                    }
            }
            when(response.fire) {
                releasePending.get := false.B
                releaseEdges := 0.U
                released := false.B
            }
        }
        io.runtimeHeld.get.valid := privateDrained && runtimeAcknowledged
        io.runtimeHeld.get.bits := runtimeEpoch
        when(io.runtimeHeld.get.valid) {
            assert(stopped && !io.retire.valid, "held runtime epoch retired architectural work")
        }
        io.maintenancePending := request || runtimeActive || releasePending.getOrElse(false.B)
    } else {
        io.bus.maintenance.ready := false.B // runtime endpoint absent in default production
        io.maintenancePending := request
    }
    io.retire := tile.io.retire
    io.trapTaken := tile.io.trapTaken; io.trapPc := tile.io.trapPc; io.trapCause := tile.io.trapCause
    io.cycles := tile.io.cycles; io.instructions := tile.io.instructions
}
