package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

class ProofOwnerMatchObservation(p: OooParams) extends Bundle {
    val query = Valid(new VirtualLoadPrecheckRequest)
    val loadPrepared = Valid(new VirtualRamLoadCertificate(p))
    val proof0 = Valid(new MemoryAddressProof(p))
    val proof1 = Valid(new MemoryAddressProof(p))
    val bound = UInt(2.W)
    val reservedCount = UInt(2.W)
    val provedCount = UInt(2.W)
    val storeResult = Bool()
    val resultValid = Bool()
    val resultFresh = Bool()
    val resultStore = Bool()
    val resultAllowed = Bool()
    val resultRow = UInt(1.W)
    val result = new MemoryAddressProof(p)
}

/** Real unchanged old bank and production bank, sharing only external stimuli.
  * Physical owner slots are independent of tokens. Read-only probes expose the
  * actual result predicate before final ownerGone priority can mask corruption.
  */
class ProofOwnerMatchPairGsim(slots: Int = 1) extends Module {
    val p = PendingStoreProofFixture.params(slots = slots)
    val io = IO(new Bundle {
        val head = Input(UInt(4.W))
        val owner0 = Input(Valid(new PendingStoreProofOwner(p)))
        val owner1 = Input(Valid(new PendingStoreProofOwner(p)))
        val owner2 = Input(Valid(new PendingStoreProofOwner(p)))
        val slot0 = Input(UInt(4.W))
        val slot1 = Input(UInt(4.W))
        val slot2 = Input(UInt(4.W))
        val clearOwners = Input(UInt(16.W))
        val queryEligible = Input(UInt(16.W))
        val pause = Input(Bool())
        val flush = Input(Bool())
        val stable = Input(Bool())
        val epoch = Input(UInt(32.W))
        val load = Input(Valid(new VirtualRamLoadCandidate(p)))
        val reply = Input(Valid(new VirtualLoadPrecheckResponse))
        val pmpCfg = Input(UInt(8.W))
        val pmpAddress = Input(UInt(54.W))
        val bind = Input(UInt(2.W))
        val consume = Input(Valid(new RobToken(p)))
        val candidate = Output(new ProofOwnerMatchObservation(p))
        val reference = Output(new ProofOwnerMatchObservation(p))
    })
    val candidate = Module(new PendingVirtualStoreProof(p))
    val reference = Module(new ReferencePendingVirtualStoreProof(p))
    candidate.io.head := io.head
    candidate.io.owners := 0.U.asTypeOf(candidate.io.owners)
    for ((owner, slot) <- Seq((io.owner0, io.slot0), (io.owner1, io.slot1), (io.owner2, io.slot2))) {
        when(owner.valid) { candidate.io.owners(slot) := owner }
    }
    candidate.io.clearOwners := io.clearOwners
    candidate.io.queryEligible := io.queryEligible
    candidate.io.pause := io.pause
    candidate.io.flushQueries := io.flush
    candidate.io.loadCandidate := io.load
    candidate.io.precheck.epoch := io.epoch
    candidate.io.precheck.stable := io.stable
    candidate.io.precheck.response := io.reply
    candidate.io.pmpState := PendingStoreProofFixture.pmp(io.pmpCfg, io.pmpAddress)
    candidate.io.privilege := 1.U
    candidate.io.bind := io.bind(slots - 1, 0)
    candidate.io.consume := io.consume
    io.candidate.query := candidate.io.precheck.request
    io.candidate.loadPrepared := candidate.io.loadPrepared
    io.candidate.proof0 := candidate.io.proofs(0)
    io.candidate.proof1 := (if (slots == 2) candidate.io.proofs(1) else 0.U.asTypeOf(io.candidate.proof1))
    io.candidate.bound := candidate.io.bound
    io.candidate.reservedCount := candidate.io.reservedCount
    io.candidate.provedCount := candidate.io.provedCount
    io.candidate.storeResult := BoringUtils.bore(candidate.storeResult)
    io.candidate.resultValid := BoringUtils.bore(candidate.translatedValid)
    io.candidate.resultFresh := BoringUtils.bore(candidate.freshResult)
    io.candidate.resultStore := BoringUtils.bore(candidate.translatedStore)
    io.candidate.resultAllowed := BoringUtils.bore(candidate.allowed)
    io.candidate.resultRow := BoringUtils.bore(candidate.translatedRow)
    io.candidate.result := BoringUtils.bore(candidate.translated)
    reference.io.head := io.head
    reference.io.owners := 0.U.asTypeOf(reference.io.owners)
    for ((owner, slot) <- Seq((io.owner0, io.slot0), (io.owner1, io.slot1), (io.owner2, io.slot2))) {
        when(owner.valid) { reference.io.owners(slot) := owner }
    }
    reference.io.clearOwners := io.clearOwners
    reference.io.queryEligible := io.queryEligible
    reference.io.pause := io.pause
    reference.io.flushQueries := io.flush
    reference.io.loadCandidate := io.load
    reference.io.precheck.epoch := io.epoch
    reference.io.precheck.stable := io.stable
    reference.io.precheck.response := io.reply
    reference.io.pmpState := PendingStoreProofFixture.pmp(io.pmpCfg, io.pmpAddress)
    reference.io.privilege := 1.U
    reference.io.bind := io.bind(slots - 1, 0)
    reference.io.consume := io.consume
    io.reference.query := reference.io.precheck.request
    io.reference.loadPrepared := reference.io.loadPrepared
    io.reference.proof0 := reference.io.proofs(0)
    io.reference.proof1 := (if (slots == 2) reference.io.proofs(1) else 0.U.asTypeOf(io.reference.proof1))
    io.reference.bound := reference.io.bound
    io.reference.reservedCount := reference.io.reservedCount
    io.reference.provedCount := reference.io.provedCount
    io.reference.storeResult := BoringUtils.bore(reference.storeResult)
    io.reference.resultValid := BoringUtils.bore(reference.translatedValid)
    io.reference.resultFresh := BoringUtils.bore(reference.freshResult)
    io.reference.resultStore := BoringUtils.bore(reference.translatedStore)
    io.reference.resultAllowed := BoringUtils.bore(reference.allowed)
    io.reference.resultRow := BoringUtils.bore(reference.translatedRow)
    io.reference.result := BoringUtils.bore(reference.translated)
}

object ProofOwnerMatchPairGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new ProofOwnerMatchPairGsim(args.lift(1).map(_.toInt).getOrElse(1)),
        Array("--target-dir", args.head))
}
