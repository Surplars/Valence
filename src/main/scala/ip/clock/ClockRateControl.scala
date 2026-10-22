package soc.ip.clock

import chisel3._
import chisel3.util._

case class ClockRatePoint(hz: Long, physicalLegal: Boolean = false,
    componentTested: Boolean = false, socSignedOff: Boolean = false) {
    require(hz > 0 && hz <= 0xffffffffL)
    def allowed: Boolean = physicalLegal && componentTested && socSignedOff
    def flags: Int = (if (physicalLegal) 1 else 0) | (if (componentTested) 2 else 0) |
        (if (socSignedOff) 4 else 0) | (if (allowed) 8 else 0)
}
case class ClockRateParams(bootHz: Long = 50000000L, minimumHz: Long = 50000000L,
    maximumHz: Long = 200000000L, stepHz: Long = 5000000L,
    points: Seq[ClockRatePoint] = Seq.empty, timeoutCycles: Int = 65536, stableCycles: Int = 3) {
    require(minimumHz > 0 && maximumHz >= minimumHz && maximumHz <= 0xffffffffL && stepHz > 0)
    require(bootHz >= minimumHz && bootHz <= maximumHz && bootHz % stepHz == 0)
    require(points.map(_.hz).distinct.size == points.size)
    require(points.forall(x => x.hz >= minimumHz && x.hz <= maximumHz && x.hz % stepHz == 0))
    require(timeoutCycles >= 8 && stableCycles >= 2 && stableCycles < timeoutCycles)
}
object ClockRateError {
    val Unsupported = 0; val Unverified = 1; val Busy = 2; val BackendAbsent = 3
    val DrainTimeout = 4; val GateTimeout = 5; val Program = 6; val LockTimeout = 7
    val ResumeTimeout = 8; val Fatal = 9
    val Count = 10
    val mask: BigInt = (BigInt(1) << Count) - 1
}
class ClockRateProgram extends Bundle {
    val hz = UInt(32.W); val token = UInt(32.W); val fallback = Bool()
}
class ClockRateProgramResult extends Bundle {
    val hz = UInt(32.W); val token = UInt(32.W); val error = Bool()
}
/** Optional AON lease protocol. Tokens identify controller transactions, not Hz.
  * The platform adapter owns the maintenance epoch and never equates terminal
  * enqueue/consumption with the later fabric-retirement acknowledgement.
  */
class ClockRateDrainTerminal extends Bundle {
    val token = UInt(32.W)
    val canceled = Bool()
    val timedOut = Bool()
}
class ClockRateDrainLease extends Bundle {
    val prepare = Decoupled(UInt(32.W))
    val resume = Decoupled(UInt(32.W))
    val cancel = Decoupled(UInt(32.W))
    val held = Flipped(Valid(UInt(32.W)))
    val abort = Flipped(Valid(UInt(32.W)))
    val terminal = Flipped(Decoupled(new ClockRateDrainTerminal))
    val retired = Flipped(Decoupled(UInt(32.W)))
    val cleanupFault = Flipped(Valid(UInt(32.W)))
}
/** Inputs belong to AON: the integration must register/synchronize them there.
  * ACKs are request-scoped private-owner, transport, fabric and AXI drain ACKs,
  * not FIFO-empty shortcuts. They remain asserted until quiesce is released.
  * resumed proves real destination edges with admission still isolated.
  * Backend operations are serialized; a timed-out operation must finish/abort
  * before another command can be accepted. Results echo exact Hz and token.
  */
class ClockRateEndpoint extends Bundle {
    val present = Input(Bool()); val drainAcks = Input(UInt(4.W))
    val gateClosed = Input(Bool()); val gateOpen = Input(Bool())
    val locked = Input(Bool()); val resumed = Input(Bool())
    val quiesce = Output(Bool()); val isolate = Output(Bool()); val clockEnable = Output(Bool())
    val program = Decoupled(new ClockRateProgram)
    val result = Flipped(Decoupled(new ClockRateProgramResult))
}
/** Independent AON transaction, no primitive/DRP magic or production ACK ties.
  * Cold reset covers every retained owner. Backend boot configuration is bootHz;
  * initial lock and domain progress are required before actualValid is exposed.
  * responseCommitted means the source consumed the response, not AON enqueue.
  * An empty/default qualification table permits no runtime rate changes.
  */
class ClockRateControl(p: ClockRateParams, externalDrainLease: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val submit = Flipped(Valid(UInt(32.W)))
        val responseCommitted = Input(Bool()); val clearErrors = Input(UInt(32.W))
        val endpoint = new ClockRateEndpoint
        val lease = if (externalDrainLease) Some(new ClockRateDrainLease) else None
        val requestError = Output(UInt(32.W))
        val requestedHz = Output(UInt(32.W)); val targetHz = Output(UInt(32.W))
        val actualHz = Output(UInt(32.W)); val actualValid = Output(Bool())
        val busy = Output(Bool()); val state = Output(UInt(4.W)); val errors = Output(UInt(32.W))
        val completed = Output(UInt(32.W)); val lastSuccess = Output(Bool())
    })
    val idle :: waitReply :: draining :: closing :: programming :: locking :: opening :: resuming :: failed :: Nil = Enum(9)
    // Keep the original Enum and every default elaboration path unchanged.
    val cleanup = 9.U(4.W)
    val retiring = 10.U(4.W)
    val state = RegInit(locking); val next = WireDefault(state); state := next
    val booting = RegInit(true.B); val recovering = RegInit(false.B)
    val everGated = RegInit(true.B); val drainProved = RegInit(false.B)
    val request = RegInit(p.bootHz.U(32.W)); val target = RegInit(p.bootHz.U(32.W))
    val actual = RegInit(p.bootHz.U(32.W)); val token = RegInit(0.U(32.W))
    val issued = RegInit(false.B); val completed = RegInit(0.U(32.W))
    val success = RegInit(false.B); val transactionFailed = RegInit(false.B)
    val timer = RegInit(0.U(log2Ceil(p.timeoutCycles + 1).W))
    val stable = RegInit(0.U(log2Ceil(p.stableCycles + 1).W))
    val expired = timer === (p.timeoutCycles - 1).U
    val events = WireDefault(VecInit(Seq.fill(ClockRateError.Count)(false.B)))
    val errors = RegInit(0.U(32.W))
    errors := (errors & ~io.clearErrors) | events.asUInt.pad(32)
    val exists = p.points.map(x => io.submit.bits === x.hz.U).foldLeft(false.B)(_ || _)
    val allowed = p.points.filter(_.allowed).map(x => io.submit.bits === x.hz.U).foldLeft(false.B)(_ || _)
    io.requestError := Mux(!io.endpoint.present, (1 << ClockRateError.BackendAbsent).U,
        Mux(state =/= idle, (1 << ClockRateError.Busy).U,
        Mux(!exists, (1 << ClockRateError.Unsupported).U,
            Mux(!allowed, (1 << ClockRateError.Unverified).U, 0.U))))
    when(io.submit.valid) {
        request := io.submit.bits
        for (bit <- 0 to ClockRateError.BackendAbsent) {
            when(io.requestError(bit)) { events(bit) := true.B }
        }
        when(io.requestError === 0.U) {
            target := io.submit.bits; recovering := false.B; transactionFailed := false.B
            everGated := false.B; drainProved := false.B; success := false.B; next := waitReply
        }
    }
    def recover(reason: Int): Unit = {
        events(reason) := true.B; transactionFailed := true.B
        when(recovering) { events(ClockRateError.Fatal) := true.B; next := failed }
            .otherwise { recovering := true.B; target := p.bootHz.U; issued := false.B; next := closing }
    }
    val leaseKeepingClock = if (externalDrainLease) next === cleanup || next === retiring else false.B
    val leaseKeepingQuiesce = if (externalDrainLease)
        next === cleanup || (next === retiring && transactionFailed && !everGated) else false.B
    val onNext = next === idle || next === waitReply || next === draining || next === opening ||
        next === resuming || (next === failed && !everGated)
    val quiesceNext = next === draining || next === closing || next === programming ||
        next === locking || next === opening || (next === failed && everGated)
    val isolateNext = (everGated || next === closing) && next =/= idle && next =/= waitReply && next =/= draining
    io.endpoint.clockEnable := RegNext(if (externalDrainLease) onNext || leaseKeepingClock else onNext, false.B)
    io.endpoint.quiesce := RegNext(if (externalDrainLease) quiesceNext || leaseKeepingQuiesce else quiesceNext, true.B)
    io.endpoint.isolate := RegNext(isolateNext, true.B)
    io.endpoint.program.valid := state === programming && !issued && io.endpoint.present
    io.endpoint.program.bits.hz := target; io.endpoint.program.bits.token := token
    io.endpoint.program.bits.fallback := recovering
    io.endpoint.result.ready := true.B // Consume stale tokens without completing a newer command.
    when(state === waitReply && io.responseCommitted) { next := draining }
    if (!externalDrainLease) {
        when(state === draining) {
            stable := Mux(io.endpoint.drainAcks.andR, stable + 1.U, 0.U)
            when(io.endpoint.drainAcks.andR && stable === (p.stableCycles - 1).U) {
                drainProved := true.B; everGated := true.B; next := closing
            }.elsewhen(expired) {
                events(ClockRateError.DrainTimeout) := true.B
                transactionFailed := true.B; next := resuming // The old clock never stopped.
            }
        }
    }
    when(state === closing) {
        when(io.endpoint.gateClosed) { token := token + 1.U; issued := false.B; next := programming }
            .elsewhen(expired) {
                events(ClockRateError.GateTimeout) := true.B; events(ClockRateError.Fatal) := true.B
                transactionFailed := true.B; next := failed
            }
    }
    when(state === programming) {
        when(io.endpoint.program.fire) { issued := true.B }
        val matching = io.endpoint.result.fire && io.endpoint.result.bits.token === token &&
            (issued || io.endpoint.program.fire)
        when(matching) {
            when(io.endpoint.result.bits.error || io.endpoint.result.bits.hz =/= target) {
                recover(ClockRateError.Program)
            }.otherwise { next := locking }
        }.elsewhen(expired) { recover(ClockRateError.Program) }
    }
    when(state === locking) {
        stable := Mux(io.endpoint.present && io.endpoint.locked, stable + 1.U, 0.U)
        when(io.endpoint.present && io.endpoint.locked && stable === (p.stableCycles - 1).U) {
            actual := target; next := opening
        }.elsewhen(expired && io.endpoint.present) { recover(ClockRateError.LockTimeout) }
    }
    when(state === opening) {
        when(io.endpoint.gateOpen && io.endpoint.locked) { next := resuming }
            .elsewhen(expired) { recover(ClockRateError.GateTimeout) }
    }
    if (!externalDrainLease) {
        when(state === resuming) {
            when(io.endpoint.resumed && !io.endpoint.drainAcks.orR && io.endpoint.locked) {
                when(!booting) { completed := completed + 1.U; success := !transactionFailed }
                booting := false.B; everGated := false.B; next := idle
            }.elsewhen(expired) {
                events(ClockRateError.ResumeTimeout) := true.B; events(ClockRateError.Fatal) := true.B
                transactionFailed := true.B; next := failed
            }
        }
    } else {
        val lease = io.lease.get
        val leaseToken = RegInit(0.U(32.W))
        val offered = RegInit(false.B)
        val resumeSent = RegInit(false.B)
        val qualificationStarted = RegInit(false.B)
        val qualificationTimer = RegInit(0.U(log2Ceil(p.timeoutCycles + 1).W))
        val qualificationCanceled = RegInit(false.B)
        val cancelAccepted = RegInit(false.B)
        when(io.submit.valid && io.requestError === 0.U) {
            leaseToken := leaseToken + 1.U
            offered := false.B; resumeSent := false.B
            qualificationStarted := false.B; qualificationTimer := 0.U
            qualificationCanceled := false.B; cancelAccepted := false.B
        }
        lease.prepare.valid := state === draining && !offered
        lease.prepare.bits := leaseToken
        when(lease.prepare.fire) { offered := true.B }
        val held = offered && lease.held.valid && lease.held.bits === leaseToken
        val abort = offered && lease.abort.valid && lease.abort.bits === leaseToken
        val cleanupFault = offered && lease.cleanupFault.valid && lease.cleanupFault.bits === leaseToken
        // R10 owns initial epoch drain and endpoint cleanup. This independent
        // phase starts on the first matching held observation, then expires N
        // AON edges later even if held is revoked or partial ACKs fluctuate.
        // Queue waiting before prepare.fire does not start either local phase.
        val qualificationExpired = qualificationStarted &&
            qualificationTimer === (p.timeoutCycles - 1).U
        when(state === draining) {
            when(held && !qualificationStarted) {
                qualificationStarted := true.B; qualificationTimer := 0.U
            }.elsewhen(qualificationStarted && qualificationTimer < p.timeoutCycles.U) {
                qualificationTimer := qualificationTimer + 1.U
            }
            stable := Mux(held && io.endpoint.drainAcks.andR, stable + 1.U, 0.U)
            // Initial-drain abort has priority and already selected R10 cancel;
            // never send a duplicate local cancellation for that transaction.
            when(abort) {
                events(ClockRateError.DrainTimeout) := true.B
                transactionFailed := true.B; next := cleanup
            }.elsewhen(qualificationExpired) {
                events(ClockRateError.DrainTimeout) := true.B
                transactionFailed := true.B; qualificationCanceled := true.B
                next := cleanup
            }.elsewhen(held && !cleanupFault && io.endpoint.drainAcks.andR && stable === (p.stableCycles - 1).U) {
                drainProved := true.B; everGated := true.B; next := closing
            }
        }
        when(cleanupFault && (state === draining || state === cleanup || state === retiring)) {
            events(ClockRateError.Fatal) := true.B
            transactionFailed := true.B
        }
        lease.cancel.valid := state === cleanup && qualificationCanceled && !cancelAccepted
        lease.cancel.bits := leaseToken
        when(lease.cancel.fire) { cancelAccepted := true.B }
        lease.resume.valid := state === resuming && !booting && offered && !resumeSent
        lease.resume.bits := leaseToken
        when(lease.resume.fire) { resumeSent := true.B }
        val terminalMatches = lease.terminal.bits.token === leaseToken
        // Local qualification expiry is a requester cancel at R10, not an R10
        // initial-drain timeout. Preserve that distinction in the terminal.
        val cleanupFlagsMatch = lease.terminal.bits.canceled &&
            lease.terminal.bits.timedOut === !qualificationCanceled
        val normalFlagsMatch = !lease.terminal.bits.canceled && !lease.terminal.bits.timedOut
        val cleanupAccepted = !qualificationCanceled || cancelAccepted
        lease.terminal.ready := offered && terminalMatches &&
            ((state === cleanup && cleanupAccepted && cleanupFlagsMatch) ||
                (state === resuming && !booting && resumeSent && normalFlagsMatch))
        when(lease.terminal.fire) {
            when(lease.terminal.bits.canceled || lease.terminal.bits.timedOut) {
                transactionFailed := true.B
            }
            when(lease.terminal.bits.timedOut) { events(ClockRateError.DrainTimeout) := true.B }
            next := retiring
        }
        // A returned runtime retirement is retained by the adapter until this
        // controller also proves its old/open clock is safe. Do not release the
        // shared rate owner merely because the CPU/fabric epoch itself retired.
        val preGateFailure = !everGated && (transactionFailed || cleanupFault)
        val progressQualified = preGateFailure || (io.endpoint.resumed && !io.endpoint.drainAcks.orR)
        lease.retired.ready := state === retiring && offered && lease.retired.bits === leaseToken &&
            io.endpoint.locked && io.endpoint.gateOpen && progressQualified
        when(lease.retired.fire) {
            completed := completed + 1.U; success := !(transactionFailed || cleanupFault)
            everGated := false.B; offered := false.B; next := idle
        }
        // Boot does not own a runtime epoch. Keep the existing startup proof.
        when(state === resuming && booting) {
            when(io.endpoint.resumed && !io.endpoint.drainAcks.orR && io.endpoint.locked) {
                booting := false.B; everGated := false.B; next := idle
            }.elsewhen(expired) {
                events(ClockRateError.ResumeTimeout) := true.B; events(ClockRateError.Fatal) := true.B
                transactionFailed := true.B; next := failed
            }
        }
        when(state === cleanup) {
            assert(io.endpoint.clockEnable && !everGated,
                "timeout cleanup stopped the original clock or followed a gated operation")
            assert(!io.endpoint.program.valid, "timeout cleanup issued a rate program")
        }
    }
    when(state =/= next || state === idle || state === waitReply || (booting && !io.endpoint.present)) {
        timer := 0.U; stable := 0.U
    }
        .otherwise { when(timer < p.timeoutCycles.U) { timer := timer + 1.U } }
    io.requestedHz := request; io.targetHz := target; io.actualHz := actual
    io.actualValid := (state === idle || state === waitReply || state === draining ||
        (state === resuming && !everGated)) && io.endpoint.present && io.endpoint.locked && io.endpoint.gateOpen
    io.busy := state =/= idle; io.state := state; io.errors := errors
    io.completed := completed; io.lastSuccess := success
    when(!reset.asBool) {
        when(io.endpoint.program.valid) {
            assert(!io.endpoint.clockEnable && io.endpoint.isolate && io.endpoint.gateClosed,
                "rate programming without a closed isolated gate")
            assert(drainProved || booting, "rate programming without real transaction drain")
        }
        when(state === waitReply || state === draining) {
            assert(io.endpoint.clockEnable, "clock stopped before source response/owner drain")
        }
        when(io.responseCommitted) { assert(state === waitReply, "response lost its reserved rate owner") }
    }
}
