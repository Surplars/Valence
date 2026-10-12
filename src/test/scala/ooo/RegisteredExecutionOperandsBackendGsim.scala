package soc.core.ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import _root_.ooo.{Lane1OwnerBackendProfile, PendingStoreProofBackendGsim}

class ExecutionBackendObservation extends Bundle {
    val enqValid = Bool()
    val enqReady = Bool()
    val deqValid = Bool()
    val deqReady = Bool()
    val occupied = Bool()
    val cancel = Bool()
    val incomingMemory = Bool()
    val incomingStore = Bool()
    val prepared = Bool()
    val inputWord0 = UInt(64.W)
    val inputWord1 = UInt(64.W)
    val inputWord2 = UInt(64.W)
    val inputWord3 = UInt(64.W)
    val inputWord4 = UInt(64.W)
    val inputWord5 = UInt(64.W)
    val inputWord6 = UInt(64.W)
    val inputWord7 = UInt(64.W)
    val inputWord8 = UInt(64.W)
    val inputWord9 = UInt(64.W)
    val heldWord0 = UInt(64.W)
    val heldWord1 = UInt(64.W)
    val heldWord2 = UInt(64.W)
    val heldWord3 = UInt(64.W)
    val heldWord4 = UInt(64.W)
    val heldWord5 = UInt(64.W)
    val heldWord6 = UInt(64.W)
    val heldWord7 = UInt(64.W)
    val heldWord8 = UInt(64.W)
    val heldWord9 = UInt(64.W)
    def inputWords: Seq[UInt] = Seq(inputWord0, inputWord1, inputWord2, inputWord3, inputWord4,
        inputWord5, inputWord6, inputWord7, inputWord8, inputWord9)
    def heldWords: Seq[UInt] = Seq(heldWord0, heldWord1, heldWord2, heldWord3, heldWord4,
        heldWord5, heldWord6, heldWord7, heldWord8, heldWord9)
}

/** Passive input/state witness on the real decoded, translated backend fixture. */
class RegisteredExecutionOperandsBackendGsim(direct: Boolean)
    extends PendingStoreProofBackendGsim(true, true, true, 2, 2, true, true, true, true, true, direct) {
    val observation0 = IO(Output(new ExecutionBackendObservation))
    val observation1 = IO(Output(new ExecutionBackendObservation))
    require(p == Lane1OwnerBackendProfile.params(true).copy(
        directRank1MemorySourceIds = true, directRegisteredExecutionOperands = direct))
    for (lane <- 0 until 2) {
        val stage = backend.executionStages(lane)
        val enq = BoringUtils.bore(stage.io.enq.bits)
        val deq = BoringUtils.bore(stage.io.deq.bits)
        val incoming = enq.asTypeOf(new IntegerExecutionOperands(p))
        require(enq.getWidth == 591 && deq.getWidth == 591)
        val out = Seq(observation0, observation1)(lane)
        out.enqValid := BoringUtils.bore(stage.io.enq.valid)
        out.enqReady := BoringUtils.bore(stage.io.enq.ready)
        out.deqValid := BoringUtils.bore(stage.io.deq.valid)
        out.deqReady := BoringUtils.bore(stage.io.deq.ready)
        out.occupied := BoringUtils.bore(stage.io.occupied)
        out.cancel := BoringUtils.bore(stage.io.cancel)
        out.incomingMemory := incoming.entry.request.memory
        out.incomingStore := incoming.entry.request.store
        out.prepared := BoringUtils.bore(backend.prepared(lane))
        val inputPadded = enq.pad(640)
        val heldPadded = deq.pad(640)
        for (word <- 0 until 10) {
            out.inputWords(word) := inputPadded(64 * word + 63, 64 * word)
            out.heldWords(word) := heldPadded(64 * word + 63, 64 * word)
        }
        when(out.enqValid) {
            assert(!incoming.entry.request.memory,
                "registered execution valid input must be non-memory")
        }
    }
}
