package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Actual retained proof bank plus an untouched r5 peer. External transactions
  * drive the independent host certificate ledger; no internal state injection.
  */
class LoadPreparedCandidateGsim(registeredQuery: Boolean) extends Module {
    val p = PendingStoreProofFixture.params(slots = 2)
    val io = IO(new Bundle {
        val load = Input(Valid(new VirtualRamLoadCandidate(p)))
        val reply = Input(Valid(new VirtualLoadPrecheckResponse))
        val epoch = Input(UInt(32.W))
        val stable = Input(Bool())
        val flushCauses = Input(UInt(4.W))
        val clear = Input(UInt(16.W))
        val consume = Input(Valid(new RobToken(p)))
        val pause = Input(Bool())
        val pmpCfg = Input(UInt(8.W))
        val query = Output(Valid(new VirtualLoadPrecheckRequest))
        val prepared = Output(Valid(new VirtualRamLoadCertificate(p)))
        val candidate = Output(Bool())
    })
    val bank = Module(new PendingVirtualStoreProof(p, registeredQuery, exposeLoadPreparedCandidate = true))
    val reference = Module(new R5PendingVirtualStoreProof(p, registeredQuery))
    bank.io.head := 0.U; reference.io.head := 0.U
    bank.io.owners := 0.U.asTypeOf(bank.io.owners); reference.io.owners := 0.U.asTypeOf(reference.io.owners)
    bank.io.queryEligible := 0.U; reference.io.queryEligible := 0.U
    bank.io.clearOwners := io.clear; reference.io.clearOwners := io.clear
    bank.io.pause := io.pause; reference.io.pause := io.pause
    bank.io.flushQueries := io.flushCauses.orR; reference.io.flushQueries := io.flushCauses.orR
    bank.io.loadCandidate := io.load; reference.io.loadCandidate := io.load
    bank.io.precheck.epoch := io.epoch; reference.io.precheck.epoch := io.epoch
    bank.io.precheck.stable := io.stable; reference.io.precheck.stable := io.stable
    bank.io.precheck.response := io.reply; reference.io.precheck.response := io.reply
    val pmp = PendingStoreProofFixture.pmp(io.pmpCfg, ((BigInt(1) << 54) - 1).U(54.W))
    bank.io.pmpState := pmp; reference.io.pmpState := pmp
    bank.io.privilege := 1.U; reference.io.privilege := 1.U
    bank.io.bind := 0.U; reference.io.bind := 0.U
    bank.io.consume := io.consume; reference.io.consume := io.consume
    assert(bank.io.precheck.request.asUInt === reference.io.precheck.request.asUInt, "candidate bank changes original query")
    assert(bank.io.loadPrepared.asUInt === reference.io.loadPrepared.asUInt, "candidate bank changes original certificate")
    assert(bank.io.proofs.asUInt === reference.io.proofs.asUInt && bank.io.bound === reference.io.bound &&
        bank.io.reservedCount === reference.io.reservedCount && bank.io.provedCount === reference.io.provedCount,
        "candidate bank changes original store state")
    io.query := bank.io.precheck.request
    io.prepared := bank.io.loadPrepared
    io.candidate := bank.io.loadPreparedCandidateValid.get
}
object LoadPreparedCandidateGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new LoadPreparedCandidateGsim(args(1) == "1"), Array("--target-dir", args.head))
}
