package soc.ip.bus

import chisel3._
import chisel3.util._

/** Always-on retention clock policy, not a clock gate or power switch.
  * The endpoint must ACK only after admission has stopped and ALL work,
  * responses, packet tails and CDC storage have drained. Wake must be held or
  * latched in the always-on domain. No reset is asserted when stopping clocks.
  * A drain timeout keeps the clock ON and inhibits retries until STOP clears.
  * The FPGA backend must use a dedicated glitchless clock buffer, not clk&CE.
  */
class PeripheralClockControl(timeoutCycles: Int = 1024, idleCycles: Int = 3) extends Module {
    require(timeoutCycles >= 8 && idleCycles >= 2 && idleCycles < timeoutCycles)
    val io = IO(new Bundle {
        val stopRequest = Input(Bool())
        val wake = Input(Bool())
        val domainAck = Input(Bool())
        val clearFault = Input(Bool())
        val quiesce = Output(Bool())
        val clockEnable = Output(Bool())
        val isolate = Output(Bool())
        val allowAdmission = Output(Bool())
        val stopped = Output(Bool())
        val fault = Output(Bool())
    })
    val ack = Module(new CdcLevel)
    ack.clockIn := clock
    ack.resetIn := reset.asBool.asAsyncReset
    ack.levelIn := io.domainAck
    val running :: draining :: stopped :: waking :: Nil = Enum(4)
    val state = RegInit(running)
    val nextState = WireDefault(state)
    state := nextState
    val timer = RegInit(0.U(log2Ceil(timeoutCycles + 1).W))
    val stable = RegInit(0.U(log2Ceil(idleCycles + 1).W))
    val fault = RegInit(false.B)
    val retryBlocked = RegInit(false.B)
    when(io.clearFault) { fault := false.B }
    when(!io.stopRequest) { retryBlocked := false.B }
    // Cross-domain level and physical gate commands must come from registers,
    // not a potentially glitching decode of multiple FSM bits.
    io.quiesce := RegNext(nextState === draining || nextState === stopped, false.B)
    io.clockEnable := RegNext(nextState =/= stopped, true.B)
    io.isolate := RegNext(nextState === stopped || nextState === waking, false.B)
    io.allowAdmission := state === running && (!io.stopRequest || io.wake || retryBlocked)
    io.stopped := state === stopped
    io.fault := fault
    when(state === running) {
        timer := 0.U
        stable := 0.U
        // Rearm only after the previous ACK has returned low. A stale ACK
        // must never satisfy a new drain request.
        when(io.stopRequest && !io.wake && !retryBlocked && !ack.levelOut) { nextState := draining }
    }
    when(state === draining) {
        when(!io.stopRequest || io.wake) { nextState := running }
            .elsewhen(ack.levelOut && stable === (idleCycles - 1).U) { nextState := stopped }
            .elsewhen(timer === (timeoutCycles - 1).U) {
                nextState := running
                fault := true.B
                retryBlocked := true.B
            }.otherwise {
                timer := timer + 1.U
                stable := Mux(ack.levelOut, stable + 1.U, 0.U)
            }
    }
    when(state === stopped && (!io.stopRequest || io.wake)) { nextState := waking; timer := 0.U }
    when(state === waking) {
        // Opening the gate is not enough: ACK must return low after actual
        // destination edges before isolation/admission can be released.
        when(!ack.levelOut) { nextState := running }
            .otherwise {
                when(timer === (timeoutCycles - 1).U) { fault := true.B }
                    .otherwise { timer := timer + 1.U }
            }
    }
}

/** This agent stays in the managed domain. Its idle input must include all
  * local engines AND pending/outstanding CDC work, not only FIFO pointers.
  * Its ACK is held high while stopped, allowing the always-on policy to wake
  * the clock and observe real destination progress before releasing isolation.
  */
class PeripheralQuiesceAck extends RawModule {
    val domainClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val quiesce = IO(Input(Bool()))
    val idle = IO(Input(Bool()))
    val stopAdmission = IO(Output(Bool()))
    val ack = IO(Output(Bool()))
    val release = Module(new CdcResetRelease)
    release.clockIn := domainClock
    release.asyncReset := commonReset
    val request = Module(new CdcLevel)
    request.clockIn := domainClock
    request.resetIn := release.resetOut
    request.levelIn := quiesce
    stopAdmission := request.levelOut
    ack := withClockAndReset(domainClock, release.resetOut) { RegNext(request.levelOut && idle, false.B) }
}
