package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

/** The actual registered-query bank and production early-payload helper. All state
  * observations are read-only. The old full-match Mux1H is a separate reference;
  * its payload is meaningful only when referencePermit is true.
  */
class BoundStorePayloadGsim(slots: Int = 2) extends Module {
    require(Set(1, 2).contains(slots))
    val p = PendingStoreProofFixture.params(slots = slots)
    val io = IO(new Bundle {
        val head = Input(UInt(4.W))
        val owner0 = Input(Valid(new PendingStoreProofOwner(p)))
        val owner1 = Input(Valid(new PendingStoreProofOwner(p)))
        val owner2 = Input(Valid(new PendingStoreProofOwner(p)))
        val clearOwners = Input(UInt(16.W))
        val queryEligible = Input(UInt(16.W))
        val pause = Input(Bool())
        val flush = Input(Bool())
        val stable = Input(Bool())
        val epoch = Input(UInt(32.W))
        val reply = Input(Valid(new VirtualLoadPrecheckResponse))
        val pmpCfg = Input(UInt(8.W))
        val bind = Input(UInt(2.W))
        val consume = Input(Valid(new RobToken(p)))
        val selectToken = Input(new RobToken(p))
        val selectAddress = Input(UInt(64.W))
        val selectSize = Input(UInt(3.W))
        val mutation = Input(UInt(4.W))
        val query = Output(Valid(new VirtualLoadPrecheckRequest))
        val proof0 = Output(Valid(new MemoryAddressProof(p)))
        val proof1 = Output(Valid(new MemoryAddressProof(p)))
        val bound = Output(UInt(2.W))
        val nonfree = Output(UInt(2.W))
        val reservedCount = Output(UInt(2.W))
        val provedCount = Output(UInt(2.W))
        val storeResult = Output(Bool())
        val resultValid = Output(Bool())
        val resultFresh = Output(Bool())
        val resultAllowed = Output(Bool())
        val resultRow = Output(UInt(1.W))
        val result = Output(new MemoryAddressProof(p))
        val exactMask = Output(UInt(2.W))
        val referencePermit = Output(Bool())
        val candidatePermit = Output(Bool())
        val reference = Output(new MemoryAddressProof(p))
        val selected = Output(new MemoryAddressProof(p))
        val singleSelected = Output(new MemoryAddressProof(p))
        val mutationChanged = Output(Bool())
    })
    val bank = Module(new PendingVirtualStoreProof(p, registerQuery = true))
    bank.io.head := io.head
    bank.io.owners := 0.U.asTypeOf(bank.io.owners)
    for (owner <- Seq(io.owner0, io.owner1, io.owner2)) {
        when(owner.valid) { bank.io.owners(owner.bits.token.index) := owner }
    }
    bank.io.clearOwners := io.clearOwners
    bank.io.queryEligible := io.queryEligible
    bank.io.pause := io.pause
    bank.io.flushQueries := io.flush
    bank.io.loadCandidate := 0.U.asTypeOf(bank.io.loadCandidate)
    bank.io.precheck.epoch := io.epoch
    bank.io.precheck.stable := io.stable
    bank.io.precheck.response := io.reply
    bank.io.pmpState := PendingStoreProofFixture.pmp(io.pmpCfg, ((BigInt(1) << 54) - 1).U(54.W))
    bank.io.privilege := 1.U
    bank.io.bind := io.bind(slots - 1, 0)
    bank.io.consume := io.consume
    io.query := bank.io.precheck.request
    io.proof0 := bank.io.proofs(0)
    io.proof1 := (if (slots == 2) bank.io.proofs(1) else 0.U.asTypeOf(io.proof1))
    io.bound := bank.io.bound
    io.nonfree := VecInit((0 until slots).map(r => BoringUtils.bore(bank.state(r)) =/= 0.U)).asUInt
    io.reservedCount := bank.io.reservedCount
    io.provedCount := bank.io.provedCount
    io.storeResult := BoringUtils.bore(bank.storeResult)
    io.resultValid := BoringUtils.bore(bank.translatedValid)
    io.resultFresh := BoringUtils.bore(bank.freshResult)
    io.resultAllowed := BoringUtils.bore(bank.allowed)
    io.resultRow := BoringUtils.bore(bank.translatedRow)
    io.result := BoringUtils.bore(bank.translated)

    // Deliberately independent old expression, including the unchanged scalar
    // permission terms from IntegerBackend. Never use it to construct new data.
    val exact = VecInit((0 until slots).map(r => bank.io.bound(r) && bank.io.proofs(r).valid &&
        bank.io.proofs(r).bits.token.asUInt === io.selectToken.asUInt &&
        bank.io.proofs(r).bits.payload.address === io.selectAddress &&
        bank.io.proofs(r).bits.payload.size === io.selectSize))
    io.exactMask := exact.asUInt
    io.referencePermit := exact.asUInt.orR
    io.reference := Mux1H(exact, bank.io.proofs.map(_.bits))
    val selected = BoundStoreProofPayload.select(bank.io.bound, bank.io.proofs.map(_.bits).toSeq,
        io.selectToken.index)
    io.singleSelected := BoundStoreProofPayload.select(bank.io.bound(0).asUInt,
        Seq(bank.io.proofs(0).bits), io.selectToken.index)
    io.selected := selected
    io.candidatePermit := exact.asUInt.orR

    // Same-binary, test-only controls. Neither bank state nor reference/host
    // expectations are changed. The host prints a reached witness before reject.
    when(io.mutation === 1.U && exact.asUInt.orR) {
        io.selected.payload.physicalAddress := selected.payload.physicalAddress ^ 8.U
    }
    when(io.mutation === 2.U) { io.selected := bank.io.proofs(0).bits }
    val weak = VecInit((0 until slots).map { r =>
        val proof = bank.io.proofs(r)
        val fullToken = proof.bits.token.asUInt === io.selectToken.asUInt
        val highTagIgnored = proof.bits.token.index === io.selectToken.index &&
            proof.bits.token.tag(62, 0) === io.selectToken.tag(62, 0)
        Mux(io.mutation === 7.U, true.B, bank.io.bound(r)) &&
            Mux(io.mutation === 6.U, true.B, proof.valid) &&
            Mux(io.mutation === 3.U, true.B, Mux(io.mutation === 8.U, highTagIgnored, fullToken)) &&
            Mux(io.mutation === 4.U, true.B, proof.bits.payload.address === io.selectAddress) &&
            Mux(io.mutation === 5.U, true.B, proof.bits.payload.size === io.selectSize)
    })
    when(io.mutation >= 3.U && io.mutation <= 8.U) { io.candidatePermit := weak.asUInt.orR }
    io.mutationChanged := io.candidatePermit =/= io.referencePermit ||
        (io.referencePermit && io.selected.asUInt =/= selected.asUInt)
}

object BoundStorePayloadGsimMain extends App {
    for (cls <- Seq(classOf[PendingVirtualStoreProof], BoundStoreProofPayload.getClass)) {
        val resource = cls.getResource("/" + cls.getName.replace('.', '/') + ".class")
        val stream = resource.openStream()
        val bytes = try stream.readAllBytes() finally stream.close()
        val digest = java.security.MessageDigest.getInstance("SHA-256").digest(bytes)
            .map(b => f"${b & 0xff}%02x").mkString
        println(s"BOUND_PAYLOAD_LOADED_CLASS ${cls.getName} $resource $digest")
    }
    ChiselStage.emitCHIRRTLFile(new BoundStorePayloadGsim(args.lift(1).map(_.toInt).getOrElse(2)),
        Array("--target-dir", args.head))
}
