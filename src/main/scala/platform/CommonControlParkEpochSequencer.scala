package soc.platform

import chisel3._
import chisel3.util._

/** Fabric-native ownership of the optional Ethernet control park.
  *
  * prepare is the actual fabric externalMaintenance.fire, not an AON request.
  * It reserves a nonzero, increasing epoch without blocking old CPU CSR work.
  * Only the real matching fabric-held and all-obligations-idle observation may
  * request park. Once requested, park remains asserted until the matching real
  * runtime terminal has actually been consumed at AON, including cancellation.
  * The terminal is retained by the runtime owner until retired (its real fire).
  *
  * parked is the live MAC control-owner predicate, not a fabricated gate ACK.
  * PHY faults therefore merely prevent qualification: cancellation must still
  * release park so the existing PHY retry lifecycle can run. They are NOT this
  * sequencer's sticky protocol faults. A normal terminal requires this epoch's
  * actual earlier outward qualification; early cancellation requires no park.
  *
  * parkReleased must be the MAC's reset-safe source-clock registered observation
  * of a low request. Both modules use the SAME fabric/source clock. releaseIssued
  * is delayed until an edge after terminal consumption deasserts request, so an
  * initially idle release indication cannot authorize retirement. This receipt
  * is not cross-domain gate feedback. Releasing park allows new CSR/MDIO/config
  * work; retirement must NOT re-drain that unrelated new work.
  *
  * Invalid, changed, withdrawn or unqualified normal terminals and stale prepares
  * fail closed until common cold reset. No clocks, resets, queues, counters or
  * data owners are otherwise changed by this module.
  */
class CommonControlParkEpochSequencer(p: CommonCpuTilePortParams) extends Module {
    require(p.runtimeMaintenance && p.runtimeCancellation && p.runtimeInterruptHold)
    val io = IO(new Bundle {
        val prepare = Input(Valid(UInt(p.maintenanceEpochBits.W)))
        val fabricHeld = Input(Valid(UInt(p.maintenanceEpochBits.W)))
        val fabricAllObligationsIdle = Input(Bool())
        val completion = Input(Valid(new CommonRuntimeCompletion(p)))
        val terminalConsumedAtAon = Input(Bool())
        val retired = Input(Bool())
        val parked = Input(Bool())
        val parkReleased = Input(Bool())
        val parkRequest = Output(Bool())
        val qualified = Valid(UInt(p.maintenanceEpochBits.W))
        val retirementPermit = Output(Bool())
        val busy = Output(Bool())
        val fault = Output(Bool())
    })

    private val owned = RegInit(false.B)
    private val epoch = RegInit(0.U(p.maintenanceEpochBits.W))
    private val lastEpoch = RegInit(0.U(p.maintenanceEpochBits.W))
    private val parkRequested = RegInit(false.B)
    private val qualifiedOnce = RegInit(false.B)
    private val terminalSeen = RegInit(false.B)
    private val terminal = Reg(new CommonRuntimeCompletion(p))
    private val decisionChosen = RegInit(false.B)
    private val releaseIssued = RegInit(false.B)
    private val failed = RegInit(false.B)

    private val prepareMatches = !owned && io.prepare.bits =/= 0.U && io.prepare.bits > lastEpoch
    private val completionMatches = owned && io.completion.bits.epoch === epoch
    private val completionAllowed = completionMatches && (io.completion.bits.canceled || qualifiedOnce)
    private val retainedCompletion = io.completion.valid && io.completion.bits.asUInt === terminal.asUInt
    private val badPrepare = io.prepare.valid && !prepareMatches
    private val badCompletion = io.completion.valid && !completionAllowed
    private val changedCompletion = terminalSeen && !retainedCompletion
    private val badConsumption = io.terminalConsumedAtAon && !(io.completion.valid && completionAllowed)
    private val protocolFault = badPrepare || badCompletion || changedCompletion || badConsumption
    private val healthy = !reset.asBool && !failed && !protocolFault
    private val realFabricHeld = io.fabricHeld.valid && io.fabricHeld.bits === epoch &&
        io.fabricAllObligationsIdle

    io.busy := owned
    io.fault := failed || protocolFault
    // A protocol failure cannot silently reopen an already parked control owner.
    // After a legitimate release, it also must not re-park newly admitted work.
    io.parkRequest := owned && parkRequested && !decisionChosen
    io.qualified.valid := healthy && owned && parkRequested && realFabricHeld && io.parked &&
        !terminalSeen && !io.completion.valid && !decisionChosen
    io.qualified.bits := epoch
    io.retirementPermit := healthy && owned && decisionChosen && releaseIssued && io.parkReleased &&
        terminalSeen && retainedCompletion

    // retired is runtimeComplete.fire, which itself depends on retirementPermit.
    // Detect an illegal fire synchronously; never feed it back combinationally
    // into healthy/permit and create a ready -> fire -> permit loop.
    private val prematureRetirement = io.retired && !io.retirementPermit
    when(protocolFault || prematureRetirement) { failed := true.B }

    when(io.prepare.valid && prepareMatches && healthy) {
        owned := true.B
        epoch := io.prepare.bits
        lastEpoch := io.prepare.bits
        parkRequested := false.B
        qualifiedOnce := false.B
        terminalSeen := false.B
        decisionChosen := false.B
        releaseIssued := false.B
    }
    // A terminal, including a late early-cancel terminal, wins over an unsent
    // park request. Old CPU CSR owners must remain serviceable until real held.
    when(healthy && owned && realFabricHeld && !terminalSeen && !io.completion.valid && !decisionChosen) {
        parkRequested := true.B
    }
    when(io.qualified.valid) { qualifiedOnce := true.B }
    when(healthy && io.completion.valid && completionAllowed && !terminalSeen) {
        terminalSeen := true.B
        terminal := io.completion.bits
    }
    when(healthy && owned && io.completion.valid && completionAllowed &&
        io.terminalConsumedAtAon && !decisionChosen) {
        decisionChosen := true.B
    }
    // The first edge after choosing the decision consumes the deasserted request
    // in the real MAC. This guard also covers cancellation that never requested
    // park, where parkReleased may have been high throughout the old epoch.
    when(healthy && owned && decisionChosen) { releaseIssued := true.B }
    when(io.retired && io.retirementPermit) {
        owned := false.B
        parkRequested := false.B
        qualifiedOnce := false.B
        terminalSeen := false.B
        decisionChosen := false.B
        releaseIssued := false.B
    }
}
