package ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** New parameterized ABI. Historical one/two-row wrappers remain untouched. */
class ThreeProofRowBankGsim(rows: Int) extends Module {
    require(Set(1, 2, 3).contains(rows))
    val p = if (rows == 3) ThreeProofRowCandidateProfile.candidate.coreParams
        else PendingStoreProofFixture.params(slots = rows).copy(pendingStoreEarlyLoadCredits = 2)
    val rowBits = math.max(1, log2Ceil(rows))
    val io = IO(new Bundle {
        val head = Input(UInt(4.W))
        val owners = Input(Vec(16, Valid(new PendingStoreProofOwner(p))))
        val queryEligible = Input(UInt(16.W))
        val clearOwners = Input(UInt(16.W))
        val pause = Input(Bool())
        val flush = Input(Bool())
        val stable = Input(Bool())
        val epoch = Input(UInt(32.W))
        val load = Input(Valid(new VirtualRamLoadCandidate(p)))
        val reply = Input(Valid(new VirtualLoadPrecheckResponse))
        val pmpCfg = Input(UInt(8.W))
        val pmpAddress = Input(UInt(54.W))
        val bind = Input(UInt(rows.W))
        val consume = Input(Valid(new RobToken(p)))
        val proofs = Output(Vec(rows, Valid(new MemoryAddressProof(p))))
        val bound = Output(UInt(rows.W))
        val states = Output(Vec(rows, UInt(2.W)))
        val reservedCount = Output(UInt(2.W))
        val provedCount = Output(UInt(2.W))
        val query = Output(Valid(new VirtualLoadPrecheckRequest))
        val loadPrepared = Output(Valid(new VirtualRamLoadCertificate(p)))
        val resultRow = Output(UInt(rowBits.W))
        val resultValid = Output(Bool())
        val resultAllowed = Output(Bool())
        val admission = Output(Bool())
        val evict = Output(Bool())
    })
    val bank = Module(new PendingVirtualStoreProof(p, registerQuery = true))
    bank.io.head := io.head
    bank.io.owners := io.owners
    bank.io.queryEligible := io.queryEligible
    bank.io.clearOwners := io.clearOwners
    bank.io.pause := io.pause
    bank.io.flushQueries := io.flush
    bank.io.precheck.stable := io.stable
    bank.io.precheck.epoch := io.epoch
    bank.io.precheck.response := io.reply
    bank.io.loadCandidate := io.load
    bank.io.pmpState := PendingStoreProofFixture.pmp(io.pmpCfg, io.pmpAddress)
    bank.io.privilege := 1.U
    bank.io.bind := io.bind
    bank.io.consume := io.consume
    io.proofs := bank.io.proofs
    io.bound := bank.io.bound
    io.reservedCount := bank.io.reservedCount
    io.provedCount := bank.io.provedCount
    io.query := bank.io.precheck.request
    io.loadPrepared := bank.io.loadPrepared
    io.states := BoringUtils.bore(bank.state)
    io.resultRow := BoringUtils.bore(bank.translatedRow)
    io.resultValid := BoringUtils.bore(bank.translatedValid)
    io.resultAllowed := BoringUtils.bore(bank.allowed)
    io.admission := BoringUtils.bore(bank.admission)
    io.evict := BoringUtils.bore(bank.evict)
}

object ThreeProofRowBankGsimMain extends App {
    require(args.length == 2 && Set("1", "2", "3").contains(args(1)))
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))), "fresh output required")
    ChiselStage.emitCHIRRTLFile(new ThreeProofRowBankGsim(args(1).toInt), Array("--target-dir", args(0)))
}
