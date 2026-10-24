package soc.platform

import chisel3._
import chisel3.util._

/** Conservative A1 park owner. Admission stops immediately, but execution and
  * retirement remain live until every architectural/execution owner drains.
  * Buffered unadmitted instructions are retained, not discarded. Cache probes
  * and interrupt transport remain live throughout the shared fabric drain.
  * One command/epoch capacity; management-only latency, no normal data-path mux.
  */
class CommonA1RuntimePark(p: CommonCpuTilePortParams) extends Module {
    require(p.runtimeMaintenance && p.runtimeCancellation)
    val io = IO(new Bundle {
        val command = Flipped(Decoupled(new CommonTileMaintenanceCommand(p)))
        val status = Decoupled(new CommonTileMaintenanceStatus(p))
        val fabricDone = Flipped(Decoupled(UInt(p.maintenanceEpochBits.W)))
        val resume = Flipped(Decoupled(UInt(p.maintenanceEpochBits.W)))
        val resumed = Decoupled(UInt(p.maintenanceEpochBits.W))
        val fenceBusy = Input(Bool())
        val architecturalIdle = Input(Bool())
        val privateIdle = Input(Bool())
        val flushDone = Input(Bool())
        val stopAdmission = Output(Bool())
        val stopped = Output(Bool())
        val flush = Output(Bool())
        val held = Valid(UInt(p.maintenanceEpochBits.W))
    })
    val active = RegInit(false.B)
    val parked = RegInit(false.B)
    val epoch = Reg(UInt(p.maintenanceEpochBits.W))
    val lastValid = RegInit(false.B)
    val offer = RegInit(false.B)
    val sent = RegInit(false.B)
    val acknowledged = RegInit(false.B)
    val resumePending = RegInit(false.B)
    val releasePending = RegInit(false.B)
    val releaseEdges = RegInit(0.U(2.W))
    // Consume the queued command even while an older FENCE owns execution.
    // Otherwise that CDC owner blocks the FENCE transport-empty proof forever.
    // Admission stops now; commit/FENCE remain live until the drain below.
    io.command.ready := !active && !releasePending &&
        !(lastValid && io.command.bits.epoch === epoch)
    when(io.command.fire) {
        assert(!io.command.bits.invalidateInstructions && !io.command.bits.invalidateTranslations,
            "A1 runtime clock park is not an architectural invalidation command")
        active := true.B; epoch := io.command.bits.epoch; lastValid := true.B
    }
    // Never freeze commitEnable before drain: accepted stores, FENCE.I and
    // precise trap/recovery must finish while the clock and backend are live.
    when(active && !parked && io.architecturalIdle && !io.fenceBusy) { parked := true.B }
    io.stopAdmission := active
    io.stopped := parked
    io.flush := active && parked
    val drained = active && parked && io.flushDone && io.privateIdle
    // This status is a retained historical drain observation, not a live gate
    // permit. Later probes still run; held below rechecks current private idle,
    // and the fabric/AON join independently checks every transport obligation.
    when(drained) { offer := true.B }
    io.status.valid := active && offer && !sent
    io.status.bits.epoch := epoch
    io.status.bits.privateOwnersDrained := true.B
    io.status.bits.dirtyWritebackCompleted := true.B
    io.status.bits.fetchQuiescent := true.B
    io.status.bits.invalidationsCompleted := false.B
    io.status.bits.holdUntilResume.get := true.B
    when(io.status.fire) { sent := true.B }
    io.fabricDone.ready := active && sent && !acknowledged && io.fabricDone.bits === epoch
    when(io.fabricDone.fire) { acknowledged := true.B }
    io.resume.ready := active && acknowledged && !resumePending && io.resume.bits === epoch
    when(io.resume.fire) { resumePending := true.B }
    when(resumePending && drained) {
        active := false.B; parked := false.B; offer := false.B; sent := false.B
        acknowledged := false.B; resumePending := false.B
        releasePending := true.B; releaseEdges := 0.U
    }
    // A release acknowledgement proves two local edges with admission reopened,
    // NOT retirement progress (which may depend on a still-closed Home).
    when(releasePending && releaseEdges =/= 2.U) { releaseEdges := releaseEdges + 1.U }
    io.resumed.valid := releasePending && releaseEdges === 2.U
    io.resumed.bits := epoch
    when(io.resumed.fire) { releasePending := false.B; releaseEdges := 0.U }
    io.held.valid := drained && acknowledged
    io.held.bits := epoch
    when(parked) { assert(active, "A1 park lost its active epoch") }
}
