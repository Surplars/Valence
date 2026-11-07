package soc.core.ooo

import chisel3._
import chisel3.util._

/** The expanded instruction and full ROB token at an actual SYSTEM start handshake. */
class ProtectedSystemStart(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    val instruction = UInt(32.W)
}

/** Existing head-serialized SYSTEM lifetime, shared with component verification.
  *
  * start and complete are accepted events, not offers. Successful completion,
  * native replies and commit backpressure cannot release the owner; only an
  * exact-token commit or the accepted exceptional completion does so. The
  * exception producer has already drained its native memory operation. No
  * cancellation, trap admission or new execution credit is implemented here.
  * Capture has the same priority over release as the backend's original state.
  */
class ProtectedSystemOwner(p: OooParams) extends Module {
    val io = IO(new Bundle {
        val start = Flipped(Valid(new ProtectedSystemStart(p)))
        val complete = Flipped(Valid(new BackendCompletion(p)))
        val commits = Input(Vec(p.commitWidth, Valid(new RobToken(p))))
        val active = Output(Bool())
        val token = Output(new RobToken(p))
        val contextMemoryEpoch = Output(Bool())
        val hMemoryEpoch = Output(Bool())
        val fpMemoryEpoch = Output(Bool())
        val retireMatches = Output(Vec(p.commitWidth, Bool()))
        val retired = Output(Bool())
    })

    val active = RegInit(false.B)
    val token = RegInit(0.U.asTypeOf(new RobToken(p)))
    // pending(head) clears at start, before a CSR updates memory context.
    // Ordinary FP arithmetic retains its existing integer-memory overlap.
    val contextBarrier = RegInit(false.B)
    val hMemory = if (p.hypervisorExperiment) Some(RegInit(false.B)) else None
    val fpMemory = if (p.fpEnabled) Some(RegInit(false.B)) else None
    io.active := active
    io.token := token
    io.contextMemoryEpoch := active && contextBarrier
    io.hMemoryEpoch := active && hMemory.getOrElse(false.B)
    io.fpMemoryEpoch := active && fpMemory.getOrElse(false.B)
    assert(!(io.hMemoryEpoch && io.fpMemoryEpoch), "one protected SYSTEM memory domain")

    // Deliberately retain the original inactive-token match semantics. FP and
    // counter retirement consumers retain their respective existing guards.
    io.retireMatches := VecInit(io.commits.map(c => c.valid && c.bits.asUInt === token.asUInt))
    io.retired := io.retireMatches.reduce(_ || _)
    when(io.complete.valid) {
        assert(active && io.complete.bits.token.asUInt === token.asUInt,
            "accepted SYSTEM completion must retain its protected full token")
        when(io.complete.bits.exception) { active := false.B }
    }
    when(io.retired) { active := false.B }
    when(io.start.valid) {
        val inst = io.start.bits.instruction
        hMemory.foreach(_ := HypervisorInstruction.memory(inst))
        fpMemory.foreach(_ := FloatingPointSubset.memory(inst))
        contextBarrier := !(p.fpEnabled.B && FloatingPointDecode.supported(inst, p.fpConfig) &&
            !FloatingPointDecode.memory(inst))
        active := true.B
        token := io.start.bits.token
    }
}
