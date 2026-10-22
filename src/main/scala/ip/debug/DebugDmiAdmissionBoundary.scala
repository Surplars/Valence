package soc.ip.debug

import chisel3._
import chisel3.util._
import soc.ip.bus.{CdcMailbox, CdcResetRelease}

class DebugDmiAdmissionTerminal(epochBits: Int) extends Bundle {
    val epoch = UInt(epochBits.W)
    val canceled = Bool()
}

/** Isolated, opt-in DMI admission barrier. Not instantiated by the production SoC.
  * The controller runs on the fixed source clock, NOT AON. Resume reopens DMI
  * admission only: the RAM loader is not a hart debug module. Accepted transport
  * work drains normally; destinationOwnersIdle covers DMI RAM work, not CPU
  * control owners or a whole-system acknowledgement.
  *
  * Every accepted epoch is nonzero and strictly increasing until common reset.
  * Link loss with an owned barrier epoch is an unbounded, observable fault:
  * only common cold reset recovers it. Transport resets never reset RAM owners
  * or barrier-control mailboxes. All four control paths carry atomic epochs.
  */
class DebugDmiAdmissionBoundary(addressBits: Int = 7, epochBits: Int = 8) extends RawModule {
    require(addressBits > 0 && epochBits > 0)
    val sourceClock = IO(Input(Clock()))
    val destinationClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val source = IO(Flipped(new DebugDmiPort(addressBits)))
    val destination = IO(new DebugDmiPort(addressBits))
    val sourceLinkUp = IO(Input(Bool()))
    val destinationLinkUp = IO(Output(Bool()))
    val destinationOwnersIdle = IO(Input(Bool()))
    val prepare = IO(Flipped(Decoupled(UInt(epochBits.W))))
    val cancel = IO(Flipped(Decoupled(UInt(epochBits.W))))
    val resume = IO(Flipped(Decoupled(UInt(epochBits.W))))
    val held = IO(Valid(UInt(epochBits.W)))
    val terminal = IO(Decoupled(new DebugDmiAdmissionTerminal(epochBits)))
    val busy = IO(Output(Bool()))
    val fault = IO(Output(Bool()))

    val crossing = Module(new DebugDmiClockBoundary(addressBits, exposeIdle = true))
    crossing.sourceClock := sourceClock
    crossing.destinationClock := destinationClock
    crossing.commonColdReset := commonColdReset
    crossing.sourceLinkUp := sourceLinkUp
    destinationLinkUp := crossing.destinationLinkUp
    destination <> crossing.destination
    source.response <> crossing.source.response
    crossing.source.request.bits := source.request.bits

    val sourceRelease = Module(new CdcResetRelease)
    sourceRelease.clockIn := sourceClock
    sourceRelease.asyncReset := commonColdReset
    val destinationRelease = Module(new CdcResetRelease)
    destinationRelease.clockIn := destinationClock
    destinationRelease.asyncReset := commonColdReset
    // Async assertion and three local release edges capture short link pulses,
    // including pulses entirely between source-clock edges.
    val transportRelease = Module(new CdcResetRelease)
    transportRelease.clockIn := sourceClock
    transportRelease.asyncReset := (commonColdReset.asBool || !sourceLinkUp).asAsyncReset

    def mailbox(forward: Boolean): CdcMailbox = {
        val m = Module(new CdcMailbox(epochBits))
        m.sourceClock := (if (forward) sourceClock else destinationClock)
        m.destinationClock := (if (forward) destinationClock else sourceClock)
        m.commonReset := commonColdReset
        m
    }
    val probe = mailbox(true)
    val proof = mailbox(false)
    val release = mailbox(true)
    val releaseAck = mailbox(false)

    val owners = withClockAndReset(sourceClock, transportRelease.resetOut) {
        val count = RegInit(0.U(4.W))
        val accepted = source.request.fire
        val returned = source.response.fire
        when(accepted && !returned) { count := count + 1.U }
        when(returned && !accepted) { count := count - 1.U }
        assert(count <= 8.U, "DMI source ownership exceeds bound")
        when(accepted && !returned) { assert(count < 8.U, "DMI ownership overflow") }
        when(returned) { assert(count =/= 0.U || accepted, "DMI response has no owner") }
        count
    }

    withClockAndReset(sourceClock, sourceRelease.resetOut) {
        val idle :: drain :: waitProof :: qualified :: waitAck :: done :: Nil = Enum(6)
        val state = RegInit(idle)
        val epoch = RegInit(0.U(epochBits.W))
        val lastEpoch = RegInit(0.U(epochBits.W))
        val decision = RegInit(false.B)
        val canceled = RegInit(false.B)
        val failed = RegInit(false.B)
        val healthy = !failed && !transportRelease.resetOut.asBool && !sourceRelease.resetOut.asBool
        val localIdle = owners === 0.U && crossing.sourceIdle.get
        busy := state =/= idle
        fault := failed
        when(state =/= idle && transportRelease.resetOut.asBool) { failed := true.B }

        prepare.ready := state === idle && healthy && prepare.bits =/= 0.U && prepare.bits > lastEpoch
        // Prepare wins over any same-cycle new request. Responses and all
        // requests already accepted by the crossing are never withdrawn.
        val admit = state === idle && healthy && !prepare.fire
        crossing.source.request.valid := source.request.valid && admit
        source.request.ready := crossing.source.request.ready && admit
        when(prepare.fire) {
            epoch := prepare.bits
            lastEpoch := prepare.bits
            decision := false.B
            canceled := false.B
            state := drain
        }
        val commandWindow = state === drain || state === waitProof || state === qualified
        cancel.ready := healthy && commandWindow && !decision && cancel.bits === epoch
        resume.ready := healthy && state === qualified && !decision && resume.bits === epoch && !cancel.fire
        when(cancel.fire) { decision := true.B; canceled := true.B }
        .elsewhen(resume.fire) { decision := true.B; canceled := false.B }

        probe.source.valid := healthy && state === drain && localIdle
        probe.source.bits := epoch
        when(probe.source.fire) { state := waitProof }
        proof.destination.ready := healthy && state === waitProof && localIdle && proof.destination.bits === epoch
        when(proof.destination.fire) { state := qualified }
        held.valid := healthy && state === qualified && localIdle
        held.bits := epoch
        release.source.valid := healthy && state === qualified && localIdle && decision
        release.source.bits := epoch
        when(release.source.fire) { state := waitAck }
        releaseAck.destination.ready := healthy && state === waitAck && releaseAck.destination.bits === epoch
        when(releaseAck.destination.fire) { state := done }
        terminal.valid := healthy && state === done
        terminal.bits.epoch := epoch
        terminal.bits.canceled := canceled
        when(terminal.fire) { state := idle }
    }

    withClockAndReset(destinationClock, destinationRelease.resetOut) {
        val owned = RegInit(false.B)
        val epoch = RegInit(0.U(epochBits.W))
        val proved = RegInit(false.B)
        val ackPending = RegInit(false.B)
        probe.destination.ready := !owned && !ackPending && !destinationRelease.resetOut.asBool
        when(probe.destination.fire) {
            owned := true.B
            epoch := probe.destination.bits
            proved := false.B
        }
        proof.source.valid := owned && !proved && crossing.destinationIdle.get && destinationOwnersIdle
        proof.source.bits := epoch
        when(proof.source.fire) { proved := true.B }
        release.destination.ready := owned && proved && !ackPending && release.destination.bits === epoch
        when(release.destination.fire) {
            owned := false.B
            ackPending := true.B
        }
        releaseAck.source.valid := ackPending
        releaseAck.source.bits := epoch
        when(releaseAck.source.fire) { ackPending := false.B }
    }
}
