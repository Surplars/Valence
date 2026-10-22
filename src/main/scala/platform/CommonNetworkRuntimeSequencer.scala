package soc.platform

import chisel3._
import chisel3.util._

/** Fabric-domain composition of existing packet-DMA and MAC admission protocols.
  * No epoch allocator, reset, clock gate or substitute RX-stop CDC is introduced.
  * Descriptor storage may remain owned but parked. Only accepted packet/memory
  * work must finish before CPU prepare; external post-stop frames are counted
  * drops by the real receiver, never promised lossless wire delivery.
  */
class CommonNetworkRuntimeSequencer(p: CommonCpuTilePortParams) extends Module {
    require(p.runtimeCancellation && p.runtimeInterruptHold)
    val io = IO(new Bundle {
        val upstreamPrepare = Flipped(Decoupled(new CommonTileMaintenanceCommand(p)))
        val downstreamPrepare = Decoupled(new CommonTileMaintenanceCommand(p))
        val dmaPause = Output(Bool())
        val txStop = Output(Bool())
        val rxStop = Output(Bool())
        val dmaTxIdle = Input(Bool())
        val dmaOwnersIdle = Input(Bool())
        val macTxDrained = Input(Bool())
        val macRxDrained = Input(Bool())
        val macReleased = Input(Bool())
        val terminalConsumedAtAon = Input(Bool())
        val retired = Input(Bool())
        val fault = Input(Bool())
        val retirementPermit = Output(Bool())
        val held = Valid(UInt(p.maintenanceEpochBits.W))
        val busy = Output(Bool())
    })
    val owned = RegInit(false.B)
    val command = Reg(new CommonTileMaintenanceCommand(p))
    val lastEpoch = RegInit(0.U(p.maintenanceEpochBits.W))
    val forwarded = RegInit(false.B)
    val prepareOffered = RegInit(false.B)
    val txClosed = RegInit(false.B)
    val releasing = RegInit(false.B)
    val opening = releasing && !io.fault
    val offer = !owned && io.upstreamPrepare.valid && !io.fault &&
        io.upstreamPrepare.bits.epoch =/= 0.U && io.upstreamPrepare.bits.epoch > lastEpoch
    // Stop wins over a new launch on the offer-capture edge. Already offered
    // memory requests and complete packet tails remain the DMA's responsibility.
    io.dmaPause := (owned && !opening) || offer
    io.rxStop := io.dmaPause
    io.txStop := owned && !opening && txClosed
    io.busy := owned
    when(offer) {
        owned := true.B; command := io.upstreamPrepare.bits
        lastEpoch := io.upstreamPrepare.bits.epoch
        forwarded := false.B; prepareOffered := false.B; txClosed := false.B; releasing := false.B
    }
    // Closing MAC first would strand an old DMA in its first control word.
    when(owned && !opening && io.dmaTxIdle) { txClosed := true.B }
    val drained = owned && txClosed && io.dmaTxIdle && io.dmaOwnersIdle &&
        io.macTxDrained && io.macRxDrained && !io.fault
    io.held.valid := drained && !opening
    io.held.bits := command.epoch
    val matchingOffer = io.upstreamPrepare.valid && io.upstreamPrepare.bits.asUInt === command.asUInt
    // Once offered, retain valid/payload even if a late fault revokes qualification.
    // The downstream debug owner handles that sticky fault and cannot prepare CPU.
    when(drained && !forwarded) { prepareOffered := true.B }
    when(prepareOffered && !forwarded && !io.fault) {
        assert(drained, "network owners reappeared after retained prepare offer")
    }
    io.downstreamPrepare.valid := prepareOffered && !forwarded && matchingOffer
    io.downstreamPrepare.bits := command
    io.upstreamPrepare.ready := io.downstreamPrepare.valid && io.downstreamPrepare.ready
    when(io.upstreamPrepare.fire) { forwarded := true.B }
    when(owned && !forwarded) {
        assert(matchingOffer, "network runtime prepare changed before actual acceptance")
    }
    assert(io.upstreamPrepare.fire === io.downstreamPrepare.fire,
        "network prepare was accepted without downstream ownership")
    // This is the actual retained AON-consumer receipt, not CPU held or a timer.
    when(owned && forwarded && io.terminalConsumedAtAon && !io.fault && !releasing) {
        releasing := true.B
        txClosed := false.B
    }
    // Existing RX-stop settled proves the release crossed and was consumed.
    // A software stop vote may remain set; runtime never overrides that policy.
    io.retirementPermit := owned && forwarded && opening && io.macReleased
    when(io.retired) {
        assert(io.retirementPermit, "network epoch retired before actual admission release")
        owned := false.B; forwarded := false.B; prepareOffered := false.B; releasing := false.B; txClosed := false.B
    }
}
