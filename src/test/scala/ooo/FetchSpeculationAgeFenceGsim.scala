package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

/** Full-width control-only fixture. The host supplies a legal allocation
  * sequence, including max-1/max/0, without truncating any production owner.
  * This is not an instruction-cache or end-to-end performance test.
  */
class FetchSpeculationAgeFenceGsim extends Module {
    val io = IO(new Bundle {
        val nextSequence = Input(UInt(64.W))
        val publicOffer = Input(Bool())
        val kill = Input(Bool())
        val drained = Input(Bool())
        val sourceSequence = Input(UInt(64.W))
        val minimumSequence = Output(UInt(64.W))
        val ageUsable = Output(Bool())
        val sourceAgeEligible = Output(Bool())
    })
    val fence = Module(new FetchSpeculationAgeFence)
    fence.io.nextSequence := io.nextSequence
    fence.io.publicOffer := io.publicOffer
    fence.io.kill := io.kill
    fence.io.drained := io.drained
    io.minimumSequence := fence.io.minimumSequence
    io.ageUsable := fence.io.ageUsable
    io.sourceAgeEligible := fence.io.ageUsable && io.sourceSequence >= fence.io.minimumSequence
}

object FetchSpeculationAgeFenceGsimMain extends App {
    require(args.length == 1, "usage: output-dir")
    ChiselStage.emitCHIRRTLFile(new FetchSpeculationAgeFenceGsim, Array("--target-dir", args.head))
}
