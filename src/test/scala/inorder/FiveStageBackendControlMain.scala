package inorder

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.inorder._

/** Exposes the actual combinational helpers, not a copied reference model. */
class FiveStageBackendControlFixture extends Module {
    val io = IO(new Bundle {
        val occupied = Input(UInt(4.W))
        val done = Input(UInt(3.W))
        val offers = Input(UInt(5.W))
        val ready = Input(UInt(3.W))
        val enabled = Input(Bool())
        val payload = Input(UInt(64.W))
        val capacity = Output(Bool())
        val dependency = Output(Bool())
        val value = Output(UInt(64.W))
        val admitted = Output(UInt(64.W))
    })
    io.capacity := I1ExecuteDatapath.backendCapacity(io.occupied(0), io.occupied(1),
        io.occupied(2), io.occupied(3), io.done(0), io.done(1), io.done(2))
    val owners = I1ExecuteDatapath.operandMasksWhen(io.enabled,
        (0 until 5).map(io.offers(_)) :+ true.B)
    val available = (0 until 3).map(io.ready(_)) ++ Seq.fill(3)(true.B)
    val values = (0 until 6).map(i => io.payload ^ (BigInt("102030405060708", 16) * (i + 1)).U(64.W))
    io.dependency := owners.zip(available).map { case (owner, ready) => owner && !ready }.reduce(_ || _)
    io.value := I1ExecuteDatapath.operand(owners, values)
    io.admitted := I1ExecuteDatapath.operand(I1ExecuteDatapath.admittedMasks(owners, available), values)
}

object FiveStageBackendControlMain extends App {
    ChiselStage.emitCHIRRTLFile(new FiveStageBackendControlFixture, Array("--target-dir", args.head))
}
