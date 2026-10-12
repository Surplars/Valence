package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

class PendingStoreRobMapObservation(p: OooParams) extends Bundle {
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

/** Actual production bank and owner wiring, checked against the frozen full-token ROB map.
  * The independent host checks the bank lifecycle and full certificate tuples.
  * Native modes retain one side only, with identical ports and all bank state observed.
  */
class PendingStoreRobMappingGsim(slots: Int = 1, nativeMode: Int = 0) extends Module {
    val p = PendingStoreProofFixture.params(slots = slots)
    val io = IO(new Bundle {
        val ownerDeny = Input(UInt(12.W))
        val mutation = Input(UInt(2.W))
        val poisonInvalid = Input(Bool())
        val loadAddress = Input(UInt(64.W))
        val loadSize = Input(UInt(2.W))
        val candidateMap = Output(UInt(16.W))
        val referenceMap = Output(UInt(16.W))
        val candidateDisjoint = Output(UInt(16.W))
        val referenceDisjoint = Output(UInt(16.W))
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
        val candidate = Output(new PendingStoreRobMapObservation(p))
        val reference = Output(new PendingStoreRobMapObservation(p))
    })
    val candidate = Module(new PendingVirtualStoreProof(p))
    candidate.io.head := io.head
    val tokens = Wire(Vec(p.robEntries, new RobToken(p)))
    val owners = Seq((io.owner0, io.slot0), (io.owner1, io.slot1), (io.owner2, io.slot2))
    for (i <- 0 until p.robEntries) {
        val selected = WireDefault(0.U.asTypeOf(io.owner0))
        val deny = WireDefault(0.U(12.W))
        for (((owner, slot), port) <- owners.zipWithIndex) {
            when(owner.valid && slot === i.U) {
                selected := owner
                deny := (if (port == 0) io.ownerDeny else 0.U)
            }
        }
        val request = WireDefault(0.U.asTypeOf(new IntegerRequest))
        request.memory := !deny(3)
        request.store := !deny(4)
        request.atomic := deny(5)
        request.system := deny(6)
        request.mulDiv := deny(7)
        request.fetchFault := deny(8)
        request.fetchPageFault := deny(9)
        request.operation := Mux(deny(10), IntegerOp.sub, IntegerOp.add)
        request.controlFlow := Mux(deny(11), ControlFlow.beq, ControlFlow.none)
        request.memorySize := selected.bits.size(1, 0)
        tokens(i) := selected.bits.token
        PendingStoreProofRobOwner.connect(candidate.io.owners(i), tokens(i), request,
            selected.valid && !deny(0), !deny(1), !deny(2), selected.bits.address, selected.bits.mask, i)
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
    io.reference := io.candidate
    val loadAligned = AlignedMemoryDisjoint.aligned(io.loadAddress, io.loadSize)
    val loadMask = AlignedMemoryDisjoint.lanes(io.loadAddress, io.loadSize)
    val rowDisjoint = candidate.io.proofs.map(proof => proof.valid && AlignedMemoryDisjoint.withLanes(
        io.loadAddress, loadAligned, loadMask, proof.bits.payload.physicalAddress(63, 3), proof.bits.payload.mask))
    val oldMaps = FrozenPendingStoreRobMapping(candidate.io.proofs.toSeq, tokens.toSeq, rowDisjoint)
    candidate.io.proofs.foreach(proof =>
        PendingStoreProofRobMapping.assertIndexedOwner(proof, tokens(proof.bits.token.index)))
    val observedProofs = WireDefault(candidate.io.proofs)
    if (nativeMode == 0) {
        // Mutations live only in the fixture; the normal path calls the production helper.
        for (r <- 0 until slots) {
            when(io.poisonInvalid && !candidate.io.proofs(r).valid) {
                observedProofs(r).bits := Fill(observedProofs(r).bits.getWidth, 1.U(1.W)).asTypeOf(observedProofs(r).bits)
            }
            when(io.mutation === 1.U) { observedProofs(r).valid := true.B }
            val proof = candidate.io.proofs(r)
            val owner = candidate.io.owners(proof.bits.token.index)
            val weakOwner = owner.valid && owner.bits.token.index === proof.bits.token.index &&
                owner.bits.address === proof.bits.payload.address && owner.bits.size === proof.bits.payload.size &&
                owner.bits.mask === proof.bits.payload.mask && proof.bits.payload.write
            when(io.mutation === 3.U) {
                observedProofs(r).valid := BoringUtils.bore(candidate.state(r)) === 3.U && weakOwner &&
                    proof.bits.epoch === io.epoch && io.stable
            }
        }
    }
    val newMap = VecInit((0 until p.robEntries).map { i =>
        observedProofs.map(proof =>
            (if (nativeMode == 0) Mux(io.mutation === 2.U, proof.valid,
                PendingStoreProofRobMapping.matches(proof, i))
            else PendingStoreProofRobMapping.matches(proof, i))).reduce(_ || _)
    }).asUInt
    val newDisjoint = VecInit((0 until p.robEntries).map { i =>
        (0 until slots).map(r => rowDisjoint(r) && PendingStoreProofRobMapping.matches(observedProofs(r), i))
            .reduce(_ || _)
    }).asUInt
    io.candidateMap := (if (nativeMode == 1) oldMaps._1 else newMap)
    io.candidateDisjoint := (if (nativeMode == 1) oldMaps._2 else newDisjoint)
    io.referenceMap := (if (nativeMode == 0) oldMaps._1 else io.candidateMap)
    io.referenceDisjoint := (if (nativeMode == 0) oldMaps._2 else io.candidateDisjoint)

}

object PendingStoreRobMappingGsimMain extends App {
    // Record the actual loaded definitions when using a bound dependency cache.
    val constructors = classOf[PendingVirtualStoreProof].getConstructors
    require(constructors.length == 1 && constructors.head.getParameterTypes.toSeq == Seq(classOf[OooParams]),
        "the fixture must load the unchanged single-parameter production bank")
    for (cls <- Seq(classOf[PendingVirtualStoreProof], classOf[PendingStoreProofOwner],
        PendingStoreProofRobOwner.getClass, PendingStoreProofRobMapping.getClass)) {
        val resource = cls.getResource("/" + cls.getName.replace('.', '/') + ".class")
        val stream = resource.openStream()
        val bytes = try stream.readAllBytes() finally stream.close()
        val digest = java.security.MessageDigest.getInstance("SHA-256").digest(bytes)
            .map(b => f"${b & 0xff}%02x").mkString
        println(s"ROB_MAP_LOADED_CLASS ${cls.getName} ${resource.toString} $digest")
    }
    ChiselStage.emitCHIRRTLFile(new PendingStoreRobMappingGsim(args.lift(1).map(_.toInt).getOrElse(1),
        args.lift(2).map(_.toInt).getOrElse(0)),
        Array("--target-dir", args.head))
}
