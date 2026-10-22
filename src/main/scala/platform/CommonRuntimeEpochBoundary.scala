package soc.platform

import chisel3._
import chisel3.util._
import soc.ip.bus.{CdcMailbox, CdcResetRelease}

class CommonRuntimeAonStatus(p: CommonCpuTilePortParams) extends Bundle {
    val token = UInt(32.W)
    val epoch = UInt(p.maintenanceEpochBits.W)
}
class CommonRuntimeAonResult(p: CommonCpuTilePortParams) extends Bundle {
    val token = UInt(32.W)
    val epoch = UInt(p.maintenanceEpochBits.W)
    val canceled = Bool()
    val timedOut = Bool()
}
private class CommonRuntimeBoundaryCommand(p: CommonCpuTilePortParams) extends Bundle {
    val operation = UInt(2.W)
    val epoch = UInt(p.maintenanceEpochBits.W)
}
private class CommonRuntimeBoundaryObservation(p: CommonCpuTilePortParams) extends Bundle {
    val epoch = UInt(p.maintenanceEpochBits.W)
    val qualified = Bool()
}

/** Default-off three-clock runtime-epoch isolation protocol, not a clock manager.
  *
  * Both request lanes are AON-native (CPU-rate and fabric-rate requesters), and
  * their 32-bit tokens are opaque response tags, not independently owned epochs.
  * Resume/cancel decisions echo both opaque token and allocated epoch so token
  * reuse cannot make an old decision match a different runtime owner.
  * One AON owner allocates monotonically increasing nonzero epochs. This first
  * isolation stage refuses wrap until common cold reset rather than pretending
  * finite-width equality can reject arbitrary ancient replay.
  *
  * CPU proof must be wired to the REAL tile's current runtimeHeld observation,
  * local transport emptiness, synchronized remote empty announcement and link.
  * Fabric proof additionally requires the REAL allObligationsIdle predicate,
  * including private/Home/DDR/native/DMA/MSI owners as applicable. The prepared
  * runtime owner must retain its admission barriers until its matching release.
  * Snapshots include false transitions and are coherent, but necessarily stale:
  * held is a matching observation, NEVER permission to close a physical gate.
  * External stopped-clock capture and peripheral admission remain separate work.
  *
  * The actual drain timeout is counted here in AON. Cancellation never withdraws
  * an accepted prepare, aborts a data owner, or fabricates successful cleanup.
  * All old clocks must keep running. The initial drain watchdog stops on the
  * first qualified observation; later false snapshots revoke held but do not
  * restart that watchdog. The requester must await fresh proof or cancel.
  * Legacy ClockRateControl is NOT integrated.
  * Only coordinated cold reset covering every owner is supported.
  */
class CommonRuntimeEpochBoundary(
    p: CommonCpuTilePortParams,
    drainTimeoutCycles: Int = 65536,
    cleanupTimeoutCycles: Int = 65536
) extends RawModule {
    require(p.runtimeMaintenance && p.runtimeCancellation && p.runtimeInterruptHold)
    require(drainTimeoutCycles >= 2 && cleanupTimeoutCycles >= 2)
    val aonClock = IO(Input(Clock()))
    val cpuClock = IO(Input(Clock()))
    val fabricClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val io = IO(new Bundle {
        val requests = Vec(2, Flipped(Decoupled(UInt(32.W))))
        val resume = Vec(2, Flipped(Decoupled(new CommonRuntimeAonStatus(p))))
        val cancel = Vec(2, Flipped(Decoupled(new CommonRuntimeAonStatus(p))))
        val held = Vec(2, Valid(new CommonRuntimeAonStatus(p)))
        val result = Vec(2, Decoupled(new CommonRuntimeAonResult(p)))
        val busy = Output(Bool())
        val activeLane = Output(UInt(1.W))
        val activeEpoch = Output(UInt(p.maintenanceEpochBits.W))
        val activeToken = Output(UInt(32.W))
        val timeoutSelected = Output(Bool())
        val proofObserved = Output(Bool())
        val drainDeadline = Output(Bool())
        val cleanupFault = Output(Bool())
        val epochExhausted = Output(Bool())
        val cpuHeld = Input(Valid(UInt(p.maintenanceEpochBits.W)))
        val fabricHeld = Input(Valid(UInt(p.maintenanceEpochBits.W)))
        val cpuLinkReady = Input(Bool())
        val cpuTransportEmpty = Input(Bool())
        val fabricEmptyInCpu = Input(Bool())
        val fabricLinkReady = Input(Bool())
        val fabricTransportEmpty = Input(Bool())
        val cpuEmptyInFabric = Input(Bool())
        val fabricAllObligationsIdle = Input(Bool())
        val externalMaintenance = Decoupled(new CommonTileMaintenanceCommand(p))
        val runtimeResume = Decoupled(UInt(p.maintenanceEpochBits.W))
        val runtimeCancel = Decoupled(UInt(p.maintenanceEpochBits.W))
        val runtimeComplete = Flipped(Decoupled(new CommonRuntimeCompletion(p)))
    })
    private def release(clock: Clock): AsyncReset = {
        val r = Module(new CdcResetRelease)
        r.clockIn := clock; r.asyncReset := commonColdReset
        r.resetOut
    }
    private val aonReset = release(aonClock)
    private val cpuReset = release(cpuClock)
    private val fabricReset = release(fabricClock)
    private def mailbox(width: Int, source: Clock, destination: Clock): CdcMailbox = {
        val m = Module(new CdcMailbox(width))
        m.sourceClock := source; m.destinationClock := destination; m.commonReset := commonColdReset
        m
    }
    private val commandType = new CommonRuntimeBoundaryCommand(p)
    private val observationType = new CommonRuntimeBoundaryObservation(p)
    private val prepareOperation = 0.U(2.W)
    private val cancelOperation = 1.U(2.W)
    private val resumeOperation = 2.U(2.W)
    private val command = mailbox(commandType.getWidth, aonClock, fabricClock)
    private val cpuArm = mailbox(p.maintenanceEpochBits, aonClock, cpuClock)
    private val cpuObservation = mailbox(observationType.getWidth, cpuClock, aonClock)
    private val fabricObservation = mailbox(observationType.getWidth, fabricClock, aonClock)
    private val terminal = mailbox((new CommonRuntimeCompletion(p)).getWidth, fabricClock, aonClock)
    private val retirement = mailbox(p.maintenanceEpochBits, fabricClock, aonClock)

    withClockAndReset(cpuClock, cpuReset) {
        val armed = RegInit(false.B)
        val epoch = RegInit(0.U(p.maintenanceEpochBits.W))
        cpuArm.destination.ready := true.B
        when(cpuArm.destination.fire) { armed := true.B; epoch := cpuArm.destination.bits }
        val observation = Wire(new CommonRuntimeBoundaryObservation(p))
        observation.epoch := epoch
        observation.qualified := io.cpuHeld.valid && io.cpuHeld.bits === epoch &&
            io.cpuLinkReady && io.cpuTransportEmpty && io.fabricEmptyInCpu
        // Send both true and false observations. CdcMailbox captures the entire
        // source-domain value atomically and keeps it stable until consumption.
        cpuObservation.source.valid := armed
        cpuObservation.source.bits := observation.asUInt
    }

    withClockAndReset(fabricClock, fabricReset) {
        val armed = RegInit(false.B)
        val epoch = RegInit(0.U(p.maintenanceEpochBits.W))
        val c = command.destination.bits.asTypeOf(new CommonRuntimeBoundaryCommand(p))
        val preparing = c.operation === prepareOperation && !armed
        val matching = armed && c.epoch === epoch
        io.externalMaintenance.valid := command.destination.valid && preparing
        io.externalMaintenance.bits.epoch := c.epoch
        io.externalMaintenance.bits.invalidateInstructions := false.B
        io.externalMaintenance.bits.invalidateTranslations := false.B
        io.runtimeCancel.valid := command.destination.valid && matching && c.operation === cancelOperation
        io.runtimeCancel.bits := c.epoch
        io.runtimeResume.valid := command.destination.valid && matching && c.operation === resumeOperation
        io.runtimeResume.bits := c.epoch
        command.destination.ready := Mux(preparing, io.externalMaintenance.ready,
            matching && Mux(c.operation === cancelOperation, io.runtimeCancel.ready,
                c.operation === resumeOperation && io.runtimeResume.ready))
        when(io.externalMaintenance.fire) { armed := true.B; epoch := c.epoch }
        val observation = Wire(new CommonRuntimeBoundaryObservation(p))
        observation.epoch := epoch
        observation.qualified := io.fabricHeld.valid && io.fabricHeld.bits === epoch &&
            io.fabricLinkReady && io.fabricTransportEmpty && io.cpuEmptyInFabric && io.fabricAllObligationsIdle
        fabricObservation.source.valid := armed
        fabricObservation.source.bits := observation.asUInt

        // Peek without consuming the real fabric terminal. 'sent' is set only
        // by source.fire; therefore sourceIdle's initial true value is NOT ACK.
        val sent = RegInit(false.B)
        val copied = Reg(new CommonRuntimeCompletion(p))
        val terminalMatches = armed && io.runtimeComplete.bits.epoch === epoch
        terminal.source.valid := io.runtimeComplete.valid && terminalMatches && !sent
        terminal.source.bits := io.runtimeComplete.bits.asUInt
        when(terminal.source.fire) { sent := true.B; copied := io.runtimeComplete.bits }
        val consumedAtAon = sent && terminal.sourceIdle
        val matchingCopy = io.runtimeComplete.bits.asUInt === copied.asUInt
        // Reserve receipt capacity before releasing the fabric owner. A faster
        // next transaction must not overwrite the prior retirement handshake.
        retirement.source.valid := consumedAtAon && io.runtimeComplete.valid && terminalMatches && matchingCopy
        retirement.source.bits := epoch
        io.runtimeComplete.ready := consumedAtAon && terminalMatches && matchingCopy && retirement.source.ready
        when(io.runtimeComplete.fire) { sent := false.B; armed := false.B }
        when(sent) {
            assert(io.runtimeComplete.valid && terminalMatches && matchingCopy,
                "fabric runtime terminal changed before end-consumption receipt")
        }
        assert(io.runtimeComplete.fire === retirement.source.fire,
            "fabric runtime retirement lost its retained receipt")
    }

    withClockAndReset(aonClock, aonReset) {
        val owned = RegInit(false.B)
        val lane = RegInit(0.U(1.W))
        val token = RegInit(0.U(32.W))
        val epoch = RegInit(0.U(p.maintenanceEpochBits.W))
        val nextEpoch = RegInit(1.U(p.maintenanceEpochBits.W))
        val exhausted = RegInit(false.B)
        val prefer = RegInit(0.U(1.W))
        val prepareSent = RegInit(false.B)
        val prepareAccepted = RegInit(false.B)
        val armSent = RegInit(false.B)
        val releaseChosen = RegInit(false.B)
        val releaseSent = RegInit(false.B)
        val canceled = RegInit(false.B)
        val timedOut = RegInit(false.B)
        val terminalConsumed = RegInit(false.B)
        val cpuProved = RegInit(false.B)
        val fabricProved = RegInit(false.B)
        val qualifiedOnce = RegInit(false.B)
        val drainTimer = RegInit(0.U(log2Ceil(drainTimeoutCycles + 1).W))
        val cleanupTimer = RegInit(0.U(log2Ceil(cleanupTimeoutCycles + 1).W))
        val cleanupFault = RegInit(false.B)
        val cpuSnapshot = cpuObservation.destination.bits.asTypeOf(new CommonRuntimeBoundaryObservation(p))
        val fabricSnapshot = fabricObservation.destination.bits.asTypeOf(new CommonRuntimeBoundaryObservation(p))
        cpuObservation.destination.ready := true.B
        fabricObservation.destination.ready := true.B
        val cpuUpdate = cpuObservation.destination.fire && owned && cpuSnapshot.epoch === epoch
        val fabricUpdate = fabricObservation.destination.fire && owned && fabricSnapshot.epoch === epoch
        when(cpuUpdate) { cpuProved := cpuSnapshot.qualified }
        when(fabricUpdate) { fabricProved := fabricSnapshot.qualified }
        val cpuCurrent = Mux(cpuUpdate, cpuSnapshot.qualified, cpuProved)
        val fabricCurrent = Mux(fabricUpdate, fabricSnapshot.qualified, fabricProved)
        val qualified = prepareAccepted && cpuCurrent && fabricCurrent
        val expired = owned && !qualifiedOnce && !releaseChosen && drainTimer === (drainTimeoutCycles - 1).U
        val selectedCancel = (0 until 2).map(i => io.cancel(i).fire).reduce(_ || _)
        val selectedResume = (0 until 2).map(i => io.resume(i).fire).reduce(_ || _)
        val chosenLane = Mux(io.requests(0).valid && io.requests(1).valid, prefer,
            Mux(io.requests(1).valid, 1.U, 0.U))
        val accepted = (0 until 2).map(i => io.requests(i).fire).reduce(_ || _)
        for (i <- 0 until 2) {
            io.requests(i).ready := !aonReset.asBool && !owned && !exhausted && chosenLane === i.U
            io.cancel(i).ready := owned && lane === i.U && io.cancel(i).bits.token === token &&
                io.cancel(i).bits.epoch === epoch && !releaseChosen
            io.resume(i).ready := owned && lane === i.U && io.resume(i).bits.token === token &&
                io.resume(i).bits.epoch === epoch && qualified && !releaseChosen && !expired && !selectedCancel
            io.held(i).valid := owned && lane === i.U && qualified && !releaseChosen && !expired
            io.held(i).bits.token := token
            io.held(i).bits.epoch := epoch
        }
        val outgoing = Wire(new CommonRuntimeBoundaryCommand(p))
        outgoing.epoch := epoch
        outgoing.operation := Mux(!prepareSent, prepareOperation, Mux(canceled, cancelOperation, resumeOperation))
        command.source.valid := owned && (!prepareSent || (prepareAccepted && releaseChosen && !releaseSent))
        command.source.bits := outgoing.asUInt
        when(command.source.fire) {
            when(!prepareSent) { prepareSent := true.B }.otherwise { releaseSent := true.B }
        }
        when(owned && prepareSent && !prepareAccepted && command.sourceIdle) { prepareAccepted := true.B }
        cpuArm.source.valid := owned && !armSent
        cpuArm.source.bits := epoch
        when(cpuArm.source.fire) { armSent := true.B }

        // Deadline priority is explicit. A matching proof arriving on this edge
        // cannot reverse the timeout decision or authorize a later normal release.
        when(owned && !releaseChosen) {
            when(expired || selectedCancel) {
                releaseChosen := true.B; canceled := true.B
                when(expired) { timedOut := true.B }
            }.elsewhen(selectedResume) { releaseChosen := true.B }
            when(!qualifiedOnce) {
                when(qualified && !expired) { qualifiedOnce := true.B }
                    .otherwise { when(drainTimer < drainTimeoutCycles.U) { drainTimer := drainTimer + 1.U } }
            }
        }
        val completion = terminal.destination.bits.asTypeOf(new CommonRuntimeCompletion(p))
        val terminalMatches = owned && releaseChosen && completion.epoch === epoch && completion.canceled === canceled
        for (i <- 0 until 2) {
            io.result(i).valid := terminal.destination.valid && terminalMatches && lane === i.U && !terminalConsumed
            io.result(i).bits.token := token
            io.result(i).bits.epoch := epoch
            io.result(i).bits.canceled := completion.canceled
            io.result(i).bits.timedOut := timedOut
        }
        terminal.destination.ready := terminalMatches && !terminalConsumed && io.result(lane).ready
        when(terminal.destination.fire) { terminalConsumed := true.B }
        retirement.destination.ready := true.B
        val retired = retirement.destination.fire && owned && retirement.destination.bits === epoch
        when(retired) {
            assert(terminalConsumed, "fabric owner retired before AON terminal consumption")
            owned := false.B
        }
        // Endpoint cleanup and post-consumption retirement can fault, but a user
        // deliberately holding result.ready low is not an endpoint cleanup fault.
        val waitingForConsumer = terminal.destination.valid && terminalMatches && !terminalConsumed
        when(owned && releaseChosen && !waitingForConsumer) {
            when(cleanupTimer === (cleanupTimeoutCycles - 1).U) { cleanupFault := true.B }
            when(cleanupTimer < cleanupTimeoutCycles.U) { cleanupTimer := cleanupTimer + 1.U }
        }.otherwise { cleanupTimer := 0.U }
        when(accepted) {
            owned := true.B; lane := chosenLane; token := io.requests(chosenLane).bits; epoch := nextEpoch
            prefer := ~chosenLane
            when(nextEpoch.andR) { exhausted := true.B }.otherwise { nextEpoch := nextEpoch + 1.U }
            prepareSent := false.B; prepareAccepted := false.B; armSent := false.B
            releaseChosen := false.B; releaseSent := false.B; canceled := false.B; timedOut := false.B
            terminalConsumed := false.B; cpuProved := false.B; fabricProved := false.B; qualifiedOnce := false.B
            drainTimer := 0.U; cleanupTimer := 0.U
        }
        io.busy := owned
        io.activeLane := lane; io.activeEpoch := epoch; io.activeToken := token
        io.timeoutSelected := timedOut; io.cleanupFault := cleanupFault; io.epochExhausted := exhausted
        io.proofObserved := owned && qualified
        io.drainDeadline := expired
        assert(!(io.requests(0).fire && io.requests(1).fire), "two rate requesters acquired one runtime owner")
        when(canceled) { assert(!selectedResume, "late drain ACK reversed sticky runtime cancellation") }
        when(terminal.destination.valid && terminalMatches) {
            assert(releaseSent, "runtime completion preceded the selected release command")
        }
    }
}
