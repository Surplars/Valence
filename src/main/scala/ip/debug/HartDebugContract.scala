package soc.ip.debug

import chisel3._
import chisel3.util._

/** Versioned INTERNAL reservation, not a DMI register map or a Debug Module.
  * No production top instantiates this interface or the unavailable terminator.
  * See docs/debug/hart-debug-contract.md before connecting any CPU signals.
  */
object HartDebugContract {
    val version = 1
    val tokenBits = 8
    val epochBits = 32
    val operationBits = 3
    val resultBits = 3
    val Halt = 0
    val Resume = 1
    val Step = 2
    val AccessRegister = 3
    val Success = 0
    val Unavailable = 1
    val Unsupported = 2
    val WrongState = 3
    val Exception = 4
    val StaleEpoch = 5

    // RISC-V abstract register numbers; merely naming them implements no CSR.
    val Dcsr = 0x7b0
    val Dpc = 0x7b1
    val Dscratch0 = 0x7b2
    val Dscratch1 = 0x7b3
    val Tselect = 0x7a0
    val Tdata1 = 0x7a1
    val Tdata2 = 0x7a2
    val Tdata3 = 0x7a3
    val Tinfo = 0x7a4
    def gpr(index: Int): Int = {
        require(index >= 0 && index < 32)
        0x1000 + index
    }
}

/** One accepted command until its response is consumed; no automatic replay.
  * Epoch is assigned by the future hart adapter's coordinated reset controller,
  * not by TCK reset. Tokens must not be reused while outstanding.
  */
class HartDebugCommand extends Bundle {
    val epoch = UInt(HartDebugContract.epochBits.W)
    val token = UInt(HartDebugContract.tokenBits.W)
    val operation = UInt(HartDebugContract.operationBits.W)
    val registerNumber = UInt(16.W)
    val write = Bool()
    val size = UInt(3.W) // aarsize: 2=32 bits, 3=64 bits; others unsupported here.
    val data = UInt(64.W)
}

class HartDebugCompletion extends Bundle {
    val epoch = UInt(HartDebugContract.epochBits.W)
    val token = UInt(HartDebugContract.tokenBits.W)
    val result = UInt(HartDebugContract.resultBits.W)
    val data = UInt(64.W)
}

/** Evidence from retirement, never inferred from an empty frontend/ROB alone.
  * Valid only after the CPU has entered actual Debug Mode. All four predicates
  * must hold together; outstanding fabric owners still drain while stopping.
  */
class HartDebugPreciseStop extends Bundle {
    val epoch = UInt(HartDebugContract.epochBits.W)
    val nextPc = UInt(64.W)
    val retirementSequence = UInt(64.W)
    val privilege = UInt(2.W)
    val cause = UInt(3.W) // dcsr.cause, not this contract's result encoding.
    val architecturalStateCommitted = Bool()
    val youngerOperationsSquashed = Bool()
    val olderMemoryEffectsDrained = Bool()
    val noOutstandingCpuTransactions = Bool()
}

/** Prospective pipeline-to-debug observation, not an immediate halt signal.
  * Identity is the allocation sequence plus epoch, not a recyclable ROB index.
  * Wrong-path/squashed observations must never become architectural triggers.
  * Trigger configuration uses tselect/tdata* abstract CSR requests above.
  */
class HartDebugTriggerObservation extends Bundle {
    val epoch = UInt(HartDebugContract.epochBits.W)
    val allocationSequence = UInt(64.W)
    val pc = UInt(64.W)
    val address = UInt(64.W)
    val triggerIndex = UInt(16.W)
    val execute = Bool()
    val load = Bool()
    val store = Bool()
    val after = Bool()
    val enterDebug = Bool() // false requests the separately implemented breakpoint exception.
}

/** DM/controller-facing orientation. Commands go to a future hart adapter.
  * A control completion acknowledges the completed transition, not acceptance.
  * Step completes only after the next instruction OR trap boundary stops again.
  */
class HartDebugControlPort extends Bundle {
    val command = Decoupled(new HartDebugCommand)
    val completion = Flipped(Decoupled(new HartDebugCompletion))
    val available = Input(Bool())
    val halted = Input(Bool())
    val resetEpoch = Input(UInt(HartDebugContract.epochBits.W))
    val preciseStop = Flipped(Valid(new HartDebugPreciseStop))
}

/** Fail-closed test/integration terminator. Capacity one, response latency one
  * cycle, at most one command per two cycles; response retained under stalls.
  * It has NO CPU, memory, reset-control or DMI ports and can never report success.
  * There is deliberately no default top-level instance and no enable flag yet.
  */
class HartDebugUnavailable extends Module {
    val io = IO(Flipped(new HartDebugControlPort))
    val pending = RegInit(false.B)
    val epoch = RegInit(0.U(HartDebugContract.epochBits.W))
    val token = RegInit(0.U(HartDebugContract.tokenBits.W))
    io.command.ready := !pending
    io.completion.valid := pending
    io.completion.bits.epoch := epoch
    io.completion.bits.token := token
    io.completion.bits.result := HartDebugContract.Unavailable.U
    io.completion.bits.data := 0.U
    io.available := false.B
    io.halted := false.B
    io.resetEpoch := 0.U
    io.preciseStop.valid := false.B
    io.preciseStop.bits := 0.U.asTypeOf(io.preciseStop.bits)
    when(io.command.fire) {
        pending := true.B
        epoch := io.command.bits.epoch
        token := io.command.bits.token
    }
    when(io.completion.fire) { pending := false.B }
}
