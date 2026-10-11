package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

/** Small saved-operation and physical-slot contract. Backend authority is supplied
  * explicitly here; genuine ROB membership/recovery is covered by the real decoder fixture.
  * No synthetic owner mutation is claimed to be reachable integrated CPU traffic.
  */
class BoundHeadStoreOverlapGsim(enabled: Boolean) extends Module {
    val p = PendingStoreProofFixture.params().copy(boundHeadStoreOverlap = enabled)
    val io = IO(new Bundle {
        val start = Flipped(Decoupled(new MemoryOperation(p)))
        val parallel = Input(Bool())
        val qualified = Input(Bool())
        val relax = Input(Valid(new RobToken(p)))
        val cancel = Input(UInt(4.W))
        val memory = new DataPort
        val complete = Decoupled(new BackendCompletion(p))
        val live = Output(UInt(4.W))
        val phase = Output(UInt(8.W))
        val owner0 = Output(new RobToken(p))
        val owner1 = Output(new RobToken(p))
        val owner2 = Output(new RobToken(p))
        val owner3 = Output(new RobToken(p))
        val compatible = Output(UInt(4.W))
        val available = Output(Bool())
        val accepted = Output(Bool())
        val chosen = Output(UInt(2.W))
        val slotParallel = Output(UInt(4.W))
        val requestOwner = Output(Valid(new RobToken(p)))
        val origin = Output(Valid(new CanonicalStoreOrigin(p)))
        val frozen = Output(Valid(new FrozenStoreProof))
        val discarded = Output(Bool())
    })
    val lsu = Module(new ParallelLoadStoreUnit(p, canonicalHandoff = true))
    lsu.io.start <> io.start
    lsu.io.parallel := io.parallel
    lsu.io.boundHeadStoreOverlapQualified.foreach(_ := io.qualified)
    lsu.io.relaxStoreOwner.get := io.relax
    lsu.io.issueDestination.foreach(_ := 0.U.asTypeOf(lsu.io.issueDestination.get))
    lsu.io.cancel := VecInit((0 until 4).map(i => io.cancel(i)))
    lsu.io.fastStoreRetire := false.B
    lsu.io.fastLoadRetire := false.B
    lsu.io.memory <> io.memory
    lsu.io.complete <> io.complete
    io.live := lsu.io.live.asUInt
    io.phase := lsu.io.phase.asUInt
    for ((out, i) <- Seq(io.owner0, io.owner1, io.owner2, io.owner3).zipWithIndex) { out := lsu.io.owner(i) }
    io.available := lsu.io.issueAvailable
    io.accepted := lsu.io.boundHeadStoreOverlapAccepted.getOrElse(false.B)
    io.chosen := BoringUtils.bore(lsu.chosen)
    io.slotParallel := BoringUtils.bore(lsu.parallel).asUInt
    io.compatible := (if (enabled) VecInit(lsu.slots.map(s =>
        BoringUtils.bore(s.io.savedLoadDisjointFromFrozenStart.get))).asUInt else 0.U)
    io.requestOwner := lsu.io.requestOwner
    io.origin := lsu.io.canonicalStoreOrigin.get
    io.frozen := lsu.io.frozenStoreProof.get
    io.discarded := lsu.io.discarded
}

object BoundHeadStoreOverlapGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)))
    ChiselStage.emitCHIRRTLFile(new BoundHeadStoreOverlapGsim(args(1) == "1"), Array("--target-dir", args.head))
}
