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
class ClockRateControl(p: ClockRateParams) extends Module {
    val io = IO(new Bundle {
        val submit = Flipped(Valid(UInt(32.W)))
        val responseCommitted = Input(Bool()); val clearErrors = Input(UInt(32.W))
        val endpoint = new ClockRateEndpoint
        val requestError = Output(UInt(32.W))
        val requestedHz = Output(UInt(32.W)); val targetHz = Output(UInt(32.W))
        val actualHz = Output(UInt(32.W)); val actualValid = Output(Bool())
        val busy = Output(Bool()); val state = Output(UInt(4.W)); val errors = Output(UInt(32.W))
        val completed = Output(UInt(32.W)); val lastSuccess = Output(Bool())
    })
    val idle :: waitReply :: draining :: closing :: programming :: locking :: opening :: resuming :: failed :: Nil = Enum(9)
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
    io.requestError := Mux(state =/= idle, (1 << ClockRateError.Busy).U,
        Mux(!exists, (1 << ClockRateError.Unsupported).U,
            Mux(!allowed, (1 << ClockRateError.Unverified).U,
                Mux(!io.endpoint.present, (1 << ClockRateError.BackendAbsent).U, 0.U))))
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
    val onNext = next === idle || next === waitReply || next === draining || next === opening ||
        next === resuming || (next === failed && !everGated)
    val quiesceNext = next === draining || next === closing || next === programming ||
        next === locking || next === opening || (next === failed && everGated)
    val isolateNext = (everGated || next === closing) && next =/= idle && next =/= waitReply && next =/= draining
    io.endpoint.clockEnable := RegNext(onNext, false.B)
    io.endpoint.quiesce := RegNext(quiesceNext, true.B)
    io.endpoint.isolate := RegNext(isolateNext, true.B)
    io.endpoint.program.valid := state === programming && !issued && io.endpoint.present
    io.endpoint.program.bits.hz := target; io.endpoint.program.bits.token := token
    io.endpoint.program.bits.fallback := recovering
    io.endpoint.result.ready := true.B // Consume stale tokens without completing a newer command.
    when(state === waitReply && io.responseCommitted) { next := draining }
    when(state === draining) {
        stable := Mux(io.endpoint.drainAcks.andR, stable + 1.U, 0.U)
        when(io.endpoint.drainAcks.andR && stable === (p.stableCycles - 1).U) {
            drainProved := true.B; everGated := true.B; next := closing
        }.elsewhen(expired) {
            events(ClockRateError.DrainTimeout) := true.B
            transactionFailed := true.B; next := resuming // The old clock never stopped.
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
        }.elsewhen(expired) { recover(ClockRateError.LockTimeout) }
    }
    when(state === opening) {
        when(io.endpoint.gateOpen && io.endpoint.locked) { next := resuming }
            .elsewhen(expired) { recover(ClockRateError.GateTimeout) }
    }
    when(state === resuming) {
        when(io.endpoint.resumed && !io.endpoint.drainAcks.orR && io.endpoint.locked) {
            when(!booting) { completed := completed + 1.U; success := !transactionFailed }
            booting := false.B; everGated := false.B; next := idle
        }.elsewhen(expired) {
            events(ClockRateError.ResumeTimeout) := true.B; events(ClockRateError.Fatal) := true.B
            transactionFailed := true.B; next := failed
        }
    }
    when(state =/= next || state === idle || state === waitReply) { timer := 0.U; stable := 0.U }
        .otherwise { when(timer < p.timeoutCycles.U) { timer := timer + 1.U } }
    io.requestedHz := request; io.targetHz := target; io.actualHz := actual
    io.actualValid := (state === idle || state === waitReply || state === draining ||
        (state === resuming && !everGated)) && io.endpoint.locked && io.endpoint.gateOpen
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
