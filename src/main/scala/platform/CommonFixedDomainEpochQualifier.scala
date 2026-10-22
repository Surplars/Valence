package soc.platform

import chisel3._
import chisel3.util._
import soc.ip.bus.{CdcLevel, CdcMailbox, CdcResetRelease}

private class CommonFixedEpochCommand(p: CommonCpuTilePortParams) extends Bundle {
    val operation = UInt(2.W)
    val epoch = UInt(p.maintenanceEpochBits.W)
}
private class CommonFixedEpochObservation(p: CommonCpuTilePortParams) extends Bundle {
    val epoch = UInt(p.maintenanceEpochBits.W)
    val qualified = Bool()
}

/** Opt-in qualification of a fixed clock domain, not a clock controller.
  *
  * prepare is the REAL fabric externalMaintenance.fire event. It reserves the
  * epoch locally, but does not send a qualification command until the real
  * matching fabric runtimeHeld and allObligationsIdle are both observed. The
  * fixed domain samples only its LOCAL idle and link predicates. Complete
  * epoch-tagged true AND false observations cross through a held-data mailbox.
  * qualified is a coherent but necessarily delayed snapshot, never a gate ACK.
  *
  * completion must be the retained real fabric runtime terminal, including its
  * canceled bit. terminalConsumedAtAon is the actual AON consumer receipt. Only
  * then is a matching decision sent to the fixed domain. Early cancellation
  * needs no qualification request or proof, but still needs a real fixed-clock
  * terminal and retirement round trip with linkReady. No clocks,
  * FIFOs, timers, data owners or admission barriers are reset/aborted here.
  * The real completion proves the OLD owners drained and the CPU resumed.
  * Retirement therefore drains control handshakes, not unrelated new traffic:
  * it does not re-require localIdle after the CPU has resumed.
  *
  * The fixed terminal mailbox is consumed first. Its actual consumption ACK,
  * guarded by terminalSent, permits fixed ownership retirement and a separate
  * returned retirement receipt. Initial mailbox sourceIdle is NEVER an ACK.
  * The fabric retains ownership until terminalRetired (real runtimeComplete.fire)
  * AND retirementPermit. New epochs cannot overtake old proof or receipt data.
  * All clocks must keep running; only coordinated common cold reset is supported.
  */
class CommonFixedDomainEpochQualifier(p: CommonCpuTilePortParams) extends RawModule {
    require(p.runtimeMaintenance && p.runtimeCancellation && p.runtimeInterruptHold)
    val fabricClock = IO(Input(Clock()))
    val fixedClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val prepare = IO(Input(Valid(UInt(p.maintenanceEpochBits.W))))
    val fabricHeld = IO(Input(Valid(UInt(p.maintenanceEpochBits.W))))
    val fabricAllObligationsIdle = IO(Input(Bool()))
    val localIdle = IO(Input(Bool()))
    val linkReady = IO(Input(Bool()))
    val completion = IO(Input(Valid(new CommonRuntimeCompletion(p))))
    val terminalConsumedAtAon = IO(Input(Bool()))
    val terminalRetired = IO(Input(Bool()))
    val qualified = IO(Valid(UInt(p.maintenanceEpochBits.W)))
    val retirementPermit = IO(Output(Bool()))
    val busy = IO(Output(Bool()))
    val fault = IO(Output(Bool()))

    private def release(clock: Clock): AsyncReset = {
        val r = Module(new CdcResetRelease)
        r.clockIn := clock; r.asyncReset := commonColdReset
        r.resetOut
    }
    private val fabricReset = release(fabricClock)
    private val fixedReset = release(fixedClock)
    private def mailbox(width: Int, from: Clock, to: Clock): CdcMailbox = {
        val m = Module(new CdcMailbox(width))
        m.sourceClock := from; m.destinationClock := to; m.commonReset := commonColdReset
        m
    }
    private val qualifyOperation = 0.U(2.W)
    private val cancelOperation = 1.U(2.W)
    private val resumeOperation = 2.U(2.W)
    private val command = mailbox((new CommonFixedEpochCommand(p)).getWidth, fabricClock, fixedClock)
    private val observation = mailbox((new CommonFixedEpochObservation(p)).getWidth, fixedClock, fabricClock)
    private val terminal = mailbox((new CommonRuntimeCompletion(p)).getWidth, fixedClock, fabricClock)
    private val retirement = mailbox((new CommonRuntimeCompletion(p)).getWidth, fixedClock, fabricClock)
    private val fabricFault = Wire(Bool())
    private val fixedFault = Wire(Bool())
    private val fixedFaultSync = Module(new CdcLevel)
    fixedFaultSync.clockIn := fabricClock; fixedFaultSync.resetIn := fabricReset
    fixedFaultSync.levelIn := fixedFault
    private val fabricFaultSync = Module(new CdcLevel)
    fabricFaultSync.clockIn := fixedClock; fabricFaultSync.resetIn := fixedReset
    fabricFaultSync.levelIn := fabricFault

    withClockAndReset(fixedClock, fixedReset) {
        val owned = RegInit(false.B)
        val epoch = RegInit(0.U(p.maintenanceEpochBits.W))
        val lastEpoch = RegInit(0.U(p.maintenanceEpochBits.W))
        val armed = RegInit(false.B)
        val qualifiedSent = RegInit(false.B)
        val decided = RegInit(false.B)
        val canceled = RegInit(false.B)
        val terminalSent = RegInit(false.B)
        val failed = RegInit(false.B)
        val incoming = command.destination.bits.asTypeOf(new CommonFixedEpochCommand(p))
        val newer = incoming.epoch =/= 0.U && incoming.epoch > lastEpoch
        val isQualify = incoming.operation === qualifyOperation
        val isCancel = incoming.operation === cancelOperation
        val isResume = incoming.operation === resumeOperation
        val prepareMatches = isQualify && !owned && newer
        val decisionMatches = !decided && ((owned && incoming.epoch === epoch &&
            (isCancel || (isResume && armed && qualifiedSent))) ||
            (!owned && newer && isCancel))
        val protocolFault = command.destination.valid && !(prepareMatches || decisionMatches)
        val healthy = !fixedReset.asBool && !failed && !fabricFaultSync.levelOut && !protocolFault
        fixedFault := failed
        when(protocolFault || fabricFaultSync.levelOut) { failed := true.B }
        // A normal decision requires this epoch's actual earlier true snapshot.
        // The real runtime completion, not new post-resume traffic, owns drain.
        command.destination.ready := healthy && (prepareMatches || decisionMatches)
        when(command.destination.fire) {
            when(!owned) { owned := true.B; epoch := incoming.epoch; lastEpoch := incoming.epoch }
            when(isQualify) { armed := true.B }.otherwise {
                decided := true.B
                canceled := isCancel
            }
        }
        val snapshot = Wire(new CommonFixedEpochObservation(p))
        snapshot.epoch := epoch
        snapshot.qualified := localIdle && linkReady
        // Stop offering new snapshots as soon as a decision reaches this end.
        // An already accepted old snapshot is drained before retirement.
        observation.source.valid := healthy && owned && armed && !decided && !command.destination.valid
        observation.source.bits := snapshot.asUInt
        when(observation.source.fire && snapshot.qualified) { qualifiedSent := true.B }
        val result = Wire(new CommonRuntimeCompletion(p))
        result.epoch := epoch; result.canceled := canceled
        terminal.source.valid := healthy && owned && decided && linkReady && !terminalSent
        terminal.source.bits := result.asUInt
        when(terminal.source.fire) { terminalSent := true.B }
        val consumedAtFabric = terminalSent && terminal.sourceIdle
        retirement.source.valid := healthy && owned && decided && consumedAtFabric &&
            observation.sourceIdle && linkReady
        retirement.source.bits := result.asUInt
        when(retirement.source.fire) {
            owned := false.B; armed := false.B; qualifiedSent := false.B; decided := false.B; terminalSent := false.B
        }
        when(retirement.source.fire) {
            assert(terminalSent && terminal.sourceIdle && observation.sourceIdle,
                "fixed epoch retired before terminal consumption and observation drain")
        }
    }

    withClockAndReset(fabricClock, fabricReset) {
        val owned = RegInit(false.B)
        val epoch = RegInit(0.U(p.maintenanceEpochBits.W))
        val lastEpoch = RegInit(0.U(p.maintenanceEpochBits.W))
        val qualifySent = RegInit(false.B)
        val proved = RegInit(false.B)
        val qualifiedOnce = RegInit(false.B)
        val decisionChosen = RegInit(false.B)
        val decisionSent = RegInit(false.B)
        val chosen = Reg(new CommonRuntimeCompletion(p))
        val terminalReceived = RegInit(false.B)
        val retiredReceived = RegInit(false.B)
        val failed = RegInit(false.B)
        val snapshot = observation.destination.bits.asTypeOf(new CommonFixedEpochObservation(p))
        val result = terminal.destination.bits.asTypeOf(new CommonRuntimeCompletion(p))
        val retired = retirement.destination.bits.asTypeOf(new CommonRuntimeCompletion(p))
        val prepareMatches = !owned && prepare.bits =/= 0.U && prepare.bits > lastEpoch
        val completionMatches = owned && completion.bits.epoch === epoch
        val matchingCompletion = completion.valid && completion.bits.asUInt === chosen.asUInt
        val observationMatches = owned && qualifySent && snapshot.epoch === epoch
        val terminalMatches = owned && decisionSent && !terminalReceived && result.asUInt === chosen.asUInt
        val retirementMatches = owned && terminalReceived && !retiredReceived && retired.asUInt === chosen.asUInt
        val badPrepare = prepare.valid && !prepareMatches
        val badCompletion = completion.valid && !completionMatches
        val changedCompletion = decisionChosen && !matchingCompletion
        val badObservation = observation.destination.valid && !observationMatches
        val badTerminal = terminal.destination.valid && !terminalMatches
        val badRetirement = retirement.destination.valid && !retirementMatches
        val prematureRetirement = terminalRetired && !(owned && retiredReceived && matchingCompletion)
        val protocolFault = badPrepare || badCompletion || changedCompletion || badObservation ||
            badTerminal || badRetirement
        val healthy = !fabricReset.asBool && !failed && !fixedFaultSync.levelOut && !protocolFault
        fabricFault := failed
        fault := failed || fixedFaultSync.levelOut || protocolFault
        busy := owned
        // terminalRetired is downstream fire and therefore depends on permit.
        // Check illegal fires synchronously; feeding them into healthy/permit
        // would create a combinational ready -> fire -> permit cycle.
        when(protocolFault || prematureRetirement || fixedFaultSync.levelOut) { failed := true.B }
        when(prepare.valid && prepareMatches && healthy) {
            owned := true.B; epoch := prepare.bits; lastEpoch := prepare.bits
            qualifySent := false.B; proved := false.B; qualifiedOnce := false.B
            decisionChosen := false.B; decisionSent := false.B
            terminalReceived := false.B; retiredReceived := false.B
        }
        val realFabricHeld = fabricHeld.valid && fabricHeld.bits === epoch && fabricAllObligationsIdle
        // An actual completion wins over an unsent qualification request.
        // Early cancel therefore has a finite, explicit fixed-domain path.
        val choose = healthy && owned && completion.valid && completionMatches && terminalConsumedAtAon &&
            !decisionChosen && (completion.bits.canceled || (qualifySent && qualifiedOnce))
        when(choose) { decisionChosen := true.B; chosen := completion.bits }
        val outgoing = Wire(new CommonFixedEpochCommand(p))
        outgoing.epoch := epoch
        outgoing.operation := Mux(decisionChosen, Mux(chosen.canceled, cancelOperation, resumeOperation), qualifyOperation)
        command.source.valid := healthy && owned && Mux(decisionChosen, !decisionSent,
            !qualifySent && realFabricHeld && !completion.valid)
        command.source.bits := outgoing.asUInt
        when(command.source.fire) {
            when(decisionChosen) { decisionSent := true.B }.otherwise { qualifySent := true.B }
        }
        observation.destination.ready := healthy && observationMatches
        when(observation.destination.fire) {
            proved := snapshot.qualified
        }
        val currentProof = Mux(observation.destination.fire, snapshot.qualified, proved)
        qualified.valid := healthy && owned && realFabricHeld && currentProof && !decisionChosen
        qualified.bits := epoch
        // This retained evidence authorizes only old-epoch completion, never
        // externally visible held or a new release after a false observation.
        when(qualified.valid) { qualifiedOnce := true.B }
        terminal.destination.ready := healthy && terminalMatches
        when(terminal.destination.fire) { terminalReceived := true.B }
        retirement.destination.ready := healthy && retirementMatches
        when(retirement.destination.fire) { retiredReceived := true.B }
        retirementPermit := healthy && owned && decisionChosen && decisionSent && terminalReceived &&
            retiredReceived && matchingCompletion
        when(terminalRetired && retirementPermit) {
            owned := false.B; qualifySent := false.B; proved := false.B; qualifiedOnce := false.B
            decisionChosen := false.B; decisionSent := false.B
            terminalReceived := false.B; retiredReceived := false.B
        }
        when(terminalRetired) {
            assert(retirementPermit, "fabric epoch retired before fixed-domain consumed retirement receipt")
        }
    }
}
