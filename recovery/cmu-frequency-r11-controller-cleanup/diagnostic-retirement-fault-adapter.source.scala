package soc.platform

import chisel3._
import chisel3.util._
import soc.ip.clock.ClockRateDrainLease

/** AON-only adapter between two optional rate-controller leases and one R10
  * runtime boundary. The boundary, not either controller, owns epoch allocation
  * and the first-qualified drain/cleanup watchdogs. Arbitration waiting before
  * requests.fire is unbounded; proof revocation does not restart that watchdog.
  * No held observation is converted into full drain ACKs or gate confirmation.
  * R10 cleanupFault is a sticky boundary-wide fault, not a per-epoch cleared
  * event. Conservatively report it for every later owned lease until coordinated
  * reset; never hide it by edge-detecting an already-set fault bit.
  */
class CommonClockRateEpochAdapter(p: CommonCpuTilePortParams) extends Module {
    val io = IO(new Bundle {
        val clients = Vec(2, Flipped(new ClockRateDrainLease))
        val requests = Vec(2, Decoupled(UInt(32.W)))
        val resume = Vec(2, Decoupled(new CommonRuntimeAonStatus(p)))
        val cancel = Vec(2, Decoupled(new CommonRuntimeAonStatus(p)))
        val held = Vec(2, Flipped(Valid(new CommonRuntimeAonStatus(p))))
        val result = Vec(2, Flipped(Decoupled(new CommonRuntimeAonResult(p))))
        val busy = Input(Bool())
        val activeLane = Input(UInt(1.W))
        val activeEpoch = Input(UInt(p.maintenanceEpochBits.W))
        val activeToken = Input(UInt(32.W))
        val drainDeadline = Input(Bool())
        val timeoutSelected = Input(Bool())
        val cleanupFault = Input(Bool())
    })
    val owned = RegInit(false.B)
    val captured = RegInit(false.B)
    val consumed = RegInit(false.B)
    val lane = RegInit(0.U(1.W))
    val token = RegInit(0.U(32.W))
    val epoch = RegInit(0.U(p.maintenanceEpochBits.W))
    val activeMatches = io.activeLane === lane && io.activeToken === token
    // On requests.fire the public activeEpoch is still the OLD owner. Capture
    // only on a later edge while the boundary presents our accepted tuple.
    when(owned && !captured && io.busy && activeMatches) {
        epoch := io.activeEpoch; captured := true.B
    }
    val matchingOwner = owned && captured && activeMatches && io.activeEpoch === epoch
    val retired = matchingOwner && consumed && !io.busy
    for (i <- 0 until 2) {
        val client = io.clients(i)
        io.requests(i).valid := !owned && client.prepare.valid
        io.requests(i).bits := client.prepare.bits
        client.prepare.ready := !owned && io.requests(i).ready
        when(io.requests(i).fire) {
            owned := true.B; captured := false.B; consumed := false.B
            lane := i.U; token := io.requests(i).bits
        }
        val selected = matchingOwner && lane === i.U
        val heldMatches = io.held(i).bits.token === token && io.held(i).bits.epoch === epoch
        client.held.valid := selected && io.busy && io.held(i).valid && heldMatches &&
            !io.drainDeadline && !io.timeoutSelected
        client.held.bits := token
        client.abort.valid := selected && io.busy && (io.drainDeadline || io.timeoutSelected)
        client.abort.bits := token
        client.cleanupFault.valid := selected && io.busy && io.cleanupFault
        client.cleanupFault.bits := token
        val resumeMatches = client.resume.bits === token
        io.resume(i).valid := selected && io.busy && client.resume.valid && resumeMatches
        io.resume(i).bits.token := token; io.resume(i).bits.epoch := epoch
        client.resume.ready := selected && io.busy && resumeMatches && io.resume(i).ready
        // R10 makes the timeout decision. There is no invented/injected cancel
        // on this path and no early withdrawal of an accepted prepare.
        io.cancel(i).valid := false.B
        io.cancel(i).bits.token := token; io.cancel(i).bits.epoch := epoch
        val resultMatches = io.result(i).bits.token === token && io.result(i).bits.epoch === epoch
        client.terminal.valid := selected && io.busy && !consumed && io.result(i).valid && resultMatches
        client.terminal.bits.token := token
        client.terminal.bits.canceled := io.result(i).bits.canceled
        client.terminal.bits.timedOut := io.result(i).bits.timedOut
        io.result(i).ready := selected && io.busy && !consumed && resultMatches && client.terminal.ready
        when(client.terminal.fire) { consumed := true.B }
        client.retired.valid := retired && lane === i.U
        client.retired.bits := token
    }
    // Runtime retirement can arrive before backend clock qualification. Keep
    // the single shared lease and old tuple until the controller consumes it.
    val retirementAccepted = io.clients.map(_.retired.fire).reduce(_ || _)
    when(retirementAccepted) { owned := false.B; captured := false.B; consumed := false.B }
    when(owned && captured && io.busy) {
        assert(activeMatches && io.activeEpoch === epoch,
            "runtime owner changed before its controller lease retired")
    }
    when(owned && captured && !io.busy) {
        assert(consumed && activeMatches && io.activeEpoch === epoch,
            "runtime boundary released before the matching terminal consumption")
    }
    assert(!(io.requests(0).fire && io.requests(1).fire), "two controllers acquired one runtime lease")
}
