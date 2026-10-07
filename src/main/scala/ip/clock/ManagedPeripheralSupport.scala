package soc.ip.clock

import chisel3._
import chisel3.util._
import soc.ip.bus._

object ManagedPeripheralSupport {
    def level(input: Bool, target: Clock, localReset: AsyncReset): Bool = {
        val sync = Module(new CdcLevel)
        sync.clockIn := target
        sync.resetIn := localReset
        sync.levelIn := input
        sync.levelOut
    }
    // Conservative budget for raw capture, CPU merge, AON policy, gate command
    // and destination release. Fixed sources only; never a DFS guarantee.
    def wakeDelay(rawHz: Int, cpuHz: Int, aonHz: Int): Int = {
        require(rawHz > 0 && cpuHz > 0 && aonHz > 0)
        val required = 24L + (12L * rawHz + cpuHz - 1) / cpuHz + (12L * rawHz + aonHz - 1) / aonHz
        val size = 1 << log2Ceil(required.max(64).toInt)
        require(size <= 1024, "source too fast for the always-on wake budget")
        size
    }
}

/** Always-running raw-domain ingress delay, not a stop-capable storage FIFO.
  * One payload per raw cycle, fixed delay, no backpressure or overwrite alias.
  * The complete active/data/error waveform is retained until wake finishes.
  * Never close the RAW source or feed it from the managed clock output.
  */
class PeripheralWakeDelay(width: Int, cycles: Int, inactive: BigInt = 0) extends RawModule {
    require(width > 0 && cycles >= 32 && cycles <= 1024 && isPow2(cycles))
    val rawClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val payload = IO(Input(UInt(width.W)))
    val active = IO(Input(Bool()))
    val quiesce = IO(Input(Bool()))
    val isolate = IO(Input(Bool()))
    val delayed = IO(Output(UInt(width.W)))
    val empty = IO(Output(Bool()))
    val wake = IO(Output(Bool()))
    val release = Module(new CdcResetRelease)
    release.clockIn := rawClock
    release.asyncReset := commonReset
    val q = ManagedPeripheralSupport.level(quiesce, rawClock, release.resetOut)
    val iso = ManagedPeripheralSupport.level(isolate, rawClock, release.resetOut)
    withClockAndReset(rawClock, release.resetOut) {
        val activity = RegInit(0.U(cycles.W))
        activity := Cat(activity(cycles - 2, 0), active)
        delayed := ShiftRegister(payload, cycles, inactive.U(width.W), true.B)
        empty := !active && !activity.orR
        val pending = RegInit(false.B)
        when(!q && !iso && !active && !activity.orR) { pending := false.B }
        when(active && (q || iso)) { pending := true.B }
        wake := pending
    }
}

/** Source-clock admission/wake proxy. Complete replies ALWAYS keep flowing
  * during drain; there is no request queue, bridge provides its one credit.
  * quiesce/isolate must already be synchronized to this source clock.
  */
class ClockRegisterAdmission(timeoutCycles: Int = 1024) extends Module {
    require(timeoutCycles >= 32)
    val io = IO(new Bundle {
        val upstream = Flipped(new RegisterPort)
        val downstream = new RegisterPort
        val quiesce = Input(Bool())
        val isolate = Input(Bool())
        val downstreamIdle = Input(Bool())
        val drained = Output(Bool())
        val wake = Output(Bool())
    })
    val blocked = io.quiesce || io.isolate
    val errorReply = RegInit(false.B)
    val timer = RegInit(0.U(log2Ceil(timeoutCycles + 1).W))
    val expired = timer === (timeoutCycles - 1).U
    val reject = blocked && expired && io.downstreamIdle && !errorReply
    when(!io.upstream.request.valid || !blocked || io.upstream.request.fire) { timer := 0.U }
        .elsewhen(!expired) { timer := timer + 1.U }
    io.downstream.request.valid := io.upstream.request.valid && !blocked && !errorReply
    io.downstream.request.bits := io.upstream.request.bits
    io.upstream.request.ready := !errorReply && ((io.downstream.request.ready && !blocked) || reject)
    io.upstream.response.valid := errorReply || io.downstream.response.valid
    io.upstream.response.bits.data := Mux(errorReply, 0.U, io.downstream.response.bits.data)
    io.upstream.response.bits.error := errorReply || io.downstream.response.bits.error
    io.downstream.response.ready := io.upstream.response.ready && !errorReply
    when(io.upstream.request.fire && reject) { errorReply := true.B }
    when(io.upstream.response.fire && errorReply) { errorReply := false.B }
    io.drained := io.quiesce && io.downstreamIdle
    val wake = RegInit(false.B)
    when(io.upstream.request.valid && blocked) { wake := true.B }
    when(io.upstream.request.fire) { wake := false.B }
    io.wake := wake
}

/** Atomic modulo32 counter bank. All fields travel in ONE acknowledged image.
  * Increments never backpressure source events. Source-idle includes unsent
  * changes AND the consumed-image ACK; destination-idle includes held deltas.
  * Require <2^32 increments per field between consumed snapshots.
  */
class CdcCounterBank(fields: Int) extends RawModule {
    require(fields > 0 && fields <= 8)
    val sourceClock = IO(Input(Clock()))
    val destinationClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val increment = IO(Input(Vec(fields, UInt(32.W))))
    val delta = IO(Decoupled(Vec(fields, UInt(32.W))))
    val sourceIdle = IO(Output(Bool()))
    val destinationIdle = IO(Output(Bool()))
    val mailbox = Module(new CdcMailbox(fields * 32))
    mailbox.sourceClock := sourceClock
    mailbox.destinationClock := destinationClock
    mailbox.commonReset := commonReset
    val sourceRelease = Module(new CdcResetRelease)
    sourceRelease.clockIn := sourceClock
    sourceRelease.asyncReset := commonReset
    withClockAndReset(sourceClock, sourceRelease.resetOut) {
        val totals = RegInit(VecInit(Seq.fill(fields)(0.U(32.W))))
        val sent = RegInit(0.U((fields * 32).W))
        for (n <- 0 until fields) totals(n) := totals(n) + increment(n)
        mailbox.source.valid := totals.asUInt =/= sent
        mailbox.source.bits := totals.asUInt
        when(mailbox.source.fire) { sent := totals.asUInt }
        sourceIdle := mailbox.sourceIdle && totals.asUInt === sent && !increment.asUInt.orR
    }
    val destinationRelease = Module(new CdcResetRelease)
    destinationRelease.clockIn := destinationClock
    destinationRelease.asyncReset := commonReset
    withClockAndReset(destinationClock, destinationRelease.resetOut) {
        val previous = RegInit(VecInit(Seq.fill(fields)(0.U(32.W))))
        val values = mailbox.destination.bits.asTypeOf(Vec(fields, UInt(32.W)))
        delta.valid := mailbox.destination.valid
        for (n <- 0 until fields) delta.bits(n) := values(n) - previous(n)
        mailbox.destination.ready := delta.ready
        when(delta.fire) { previous := values }
        destinationIdle := mailbox.destinationIdle
    }
}
