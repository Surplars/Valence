package soc.platform

import chisel3._
import chisel3.util._
import soc.ip.ethernet._

/** Opt-in fabric translation of the EXISTING network/control epoch owners.
  * This allocates serials, not epochs or AON decisions. The network sequencer
  * closes real DMA producers before TX; the control sequencer owns raw held.
  * Every proof includes the full last command, its actual receipt and matching
  * coherent observation. Old observations are drained, never used as new proof.
  *
  * PARK is intentionally issued only when ready, with live closure witnesses.
  * FixedMacBoundary.ready has no command.valid dependence: its idle predicates
  * are registered ownership, and request offer fences do not depend on ready.
  * This specific composition avoids retaining a PARK offer across cancellation
  * and a new CSR request. It is not a general Decoupled producer recipe.
  */
class CommonFixedMacRuntimeAdapter(p: CommonCpuTilePortParams) extends Module {
    require(p.maintenanceEpochBits <= 16)
    val io = IO(new Bundle {
        val owner = Input(Valid(UInt(p.maintenanceEpochBits.W)))
        val rxStop = Input(Bool())
        val txStop = Input(Bool())
        val park = Input(Bool())
        val txProducersClosed = Input(Bool())
        val controlProducersClosed = Input(Bool())
        val terminalConsumedAtAon = Input(Bool())
        val retired = Input(Bool())
        val boundary = Flipped(new FixedMacRuntimePort)
        val txDrained = Output(Bool())
        val rxDrained = Output(Bool())
        val parked = Output(Bool())
        val released = Output(Bool())
        val busy = Output(Bool())
        val fault = Output(Bool())
    })
    private val owned = RegInit(false.B)
    private val epoch = RegInit(0.U(16.W))
    private val lastEpoch = RegInit(0.U(16.W))
    private val serial = RegInit(0.U(16.W))
    private val current = RegInit(0.U.asTypeOf(new FixedMacCommand))
    private val currentValid = RegInit(false.B)
    private val waitingReceipt = RegInit(false.B)
    private val receiptSeen = RegInit(false.B)
    private val snapshot = RegInit(0.U.asTypeOf(new FixedMacObservation))
    private val snapshotValid = RegInit(false.B)
    private val terminalSeen = RegInit(false.B)
    private val offered = RegInit(false.B)
    private val offer = Reg(new FixedMacCommand)
    private val failed = RegInit(false.B)

    private val target = Wire(new FixedMacCommand)
    target.epoch := epoch
    target.serial := serial + 1.U
    target.rxStop := io.rxStop
    target.txStop := io.txStop
    target.park := io.park
    private val votesMatch = currentValid && current.rxStop === target.rxStop &&
        current.txStop === target.txStop && current.park === target.park
    private val need = owned && !votesMatch
    private val targetRelease = !target.rxStop && !target.txStop && !target.park
    private val releaseAllowed = terminalSeen || io.terminalConsumedAtAon
    private val badOwner = io.owner.valid &&
        Mux(owned, io.owner.bits =/= epoch, io.owner.bits === 0.U || io.owner.bits <= lastEpoch)
    private val badReceipt = io.boundary.consumed.valid &&
        (!owned || !currentValid || !waitingReceipt || io.boundary.consumed.bits.asUInt =/= current.asUInt)
    private val observationMatches = currentValid &&
        io.boundary.observation.bits.command.asUInt === current.asUInt
    private val badObservation = io.boundary.observation.valid &&
        (!owned || !currentValid || io.boundary.observation.bits.command.epoch =/= epoch ||
            io.boundary.observation.bits.command.serial > serial ||
            (io.boundary.observation.bits.command.serial === serial && !observationMatches))
    private val exhausted = need && !waitingReceipt && !offered && serial === "hffff".U
    // Exhaustion depends on desired network votes, which themselves observe our
    // fault. Register this fail-closed condition rather than feed a fault loop.
    private val protocolFault = badOwner || badReceipt || badObservation
    private val serialAvailable = serial =/= "hffff".U
    private val healthy = !reset.asBool && !failed && !protocolFault
    io.fault := failed || protocolFault
    io.busy := owned
    io.boundary.txProducersClosed := io.txProducersClosed
    io.boundary.controlProducersClosed := io.controlProducersClosed
    // In particular this never waits for the release receipt. The final release
    // receipt itself waits for this snapshot's actual consumption in the CDC.
    io.boundary.observation.ready := !reset.asBool && !failed
    io.boundary.consumed.ready := healthy

    private val eligible = (!target.txStop || io.txProducersClosed) &&
        (!targetRelease || releaseAllowed)
    private val atomicPark = healthy && serialAvailable && need && !waitingReceipt && !offered && target.park &&
        eligible && io.controlProducersClosed
    io.boundary.command.bits := Mux(offered, offer, target)
    io.boundary.command.valid := healthy &&
        (offered || (atomicPark && io.boundary.command.ready))
    when(healthy && serialAvailable && need && !waitingReceipt && !offered && !target.park && eligible) {
        offer := target
        offered := true.B
    }
    when(io.boundary.command.fire) {
        current := io.boundary.command.bits
        currentValid := true.B
        serial := io.boundary.command.bits.serial
        waitingReceipt := true.B
        receiptSeen := false.B
        snapshotValid := false.B
        offered := false.B
        when(io.boundary.command.bits.park) {
            assert(io.controlProducersClosed && io.txProducersClosed,
                "fixed MAC PARK must atomically consume live real owner witnesses")
        }
    }
    when(io.boundary.consumed.fire) {
        waitingReceipt := false.B
        receiptSeen := true.B
    }
    when(io.boundary.observation.fire && observationMatches && !io.boundary.command.fire) {
        snapshot := io.boundary.observation.bits
        snapshotValid := true.B
    }
    // A same-command false observation immediately withdraws an older true
    // snapshot. A stale serial is consumed but cannot overwrite current proof.
    private val liveObservation = io.boundary.observation.valid && observationMatches
    private val proof = Mux(liveObservation, io.boundary.observation.bits, snapshot)
    private val proofValid = healthy && owned && currentValid && receiptSeen &&
        (snapshotValid || liveObservation)
    // A newly desired PARK must not revoke the admission proof used to obtain
    // its raw fabric-held witness. Full command matching still authenticates
    // every snapshot; only the downstream function's requested votes differ.
    private val admissionVotesMatch = current.rxStop === target.rxStop && current.txStop === target.txStop
    io.txDrained := proofValid && admissionVotesMatch && current.txStop && proof.txDrained &&
        io.boundary.fabricTxStorageIdle
    io.rxDrained := proofValid && admissionVotesMatch && current.rxStop && proof.rxDrained &&
        io.boundary.fabricRxConsumersIdle
    io.parked := proofValid && votesMatch && current.park && proof.parked && io.boundary.fabricCsrIdle
    // Do not re-drain newly admitted packets/CSR after consuming release. The
    // opt-in boundary's delayed receipt already proves old observation drainage.
    io.released := proofValid && votesMatch && targetRelease && releaseAllowed && proof.released

    when(protocolFault || exhausted || (io.retired && !io.released)) { failed := true.B }
    when(io.owner.valid && !owned && healthy) {
        owned := true.B
        epoch := io.owner.bits
        lastEpoch := io.owner.bits
        currentValid := false.B
        snapshotValid := false.B
        receiptSeen := false.B
        terminalSeen := false.B
    }
    when(owned && io.terminalConsumedAtAon) { terminalSeen := true.B }
    when(io.retired && io.released) {
        owned := false.B
        currentValid := false.B
        snapshotValid := false.B
        receiptSeen := false.B
        terminalSeen := false.B
    }
}
