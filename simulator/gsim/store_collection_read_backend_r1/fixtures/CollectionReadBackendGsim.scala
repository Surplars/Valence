package ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Actual decoded-request backend, including rename, ROB, issue, LSU, request
  * queue and StoreBuffer. No test-authored MemoryOperation/head token input.
  * Environment ports remain explicit; the host must obey their normal contracts.
  */
class CollectionReadBackendGsim(enabled: Boolean) extends Module {
    val p = CollectionReadProfileV2.config.coreParams.copy(postedCollectionReadProgress = enabled)
    val backend = Module(new IntegerBackend(p, canonicalHandoff =
        CollectionReadProfileV2.config.independentDemandAdmission && p.canonicalVirtualStoreOverlap,
        registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent,
        retirementSlotIdentity = p.retirementSlotIdentity,
        preselectRedirectTokenMatches = false, shadowEarlyProofBind = true,
        proofBankQuiesceIntent = true, proofBankOwnerCleanup = true,
        factorPreparedStorePool = true, projectedRequestHead = true,
        registeredMemoryPreparationDescriptor = true, backendNaturalAlignedPmp = true))
    val io = IO(chiselTypeOf(backend.io))
    io <> backend.io
    val observation = IO(Output(new Bundle {
        val headValid = Bool()
        val headDone = Bool()
        val headPending = Bool()
        val headToken = new RobToken(p)
        val headRequest = new IntegerRequest
        val start = Valid(new MemoryOperation(p))
        val startReady = Bool()
        val eligible = Bool()
        val postedBusy = Bool()
        val lsuRequest = Valid(new DataRequest(p.dataReturnHandleBits))
        val lsuRequestReady = Bool()
        val lsuQualification = Bool()
    }))
    observation.headValid := BoringUtils.bore(backend.ledger.io.headValid)
    observation.headDone := BoringUtils.bore(backend.ledger.io.headDone)
    val observedPending = BoringUtils.bore(backend.pending)
    val observedHead = BoringUtils.bore(backend.head)
    observation.headPending := observedPending(observedHead)
    observation.headToken := BoringUtils.bore(backend.headRenamed.token)
    observation.headRequest := BoringUtils.bore(backend.headRequest)
    observation.start.valid := BoringUtils.bore(backend.lsu.io.start.valid)
    observation.start.bits := BoringUtils.bore(backend.lsu.io.start.bits)
    observation.startReady := BoringUtils.bore(backend.lsu.io.start.ready)
    observation.eligible := BoringUtils.bore(backend.collectionReadEligible)
    observation.postedBusy := BoringUtils.bore(backend.postedBusy)
    observation.lsuRequest.valid := BoringUtils.bore(backend.lsu.io.memory.request.valid)
    observation.lsuRequest.bits := BoringUtils.bore(backend.lsu.io.memory.request.bits)
    observation.lsuRequestReady := BoringUtils.bore(backend.lsu.io.memory.request.ready)
    observation.lsuQualification := (if (enabled) BoringUtils.bore(backend.lsu.io.collectionHeadRead.get) else false.B)
    require(io.memory.request.bits.getWidth == 184)
}

object CollectionReadBackendGsimMain extends App {
    require(args.length == 3)
    val out = java.nio.file.Path.of(args(0)); java.nio.file.Files.createDirectories(out)
    val enabled = args(1).toBoolean
    val p = CollectionReadProfileV2.config.coreParams.copy(postedCollectionReadProgress = enabled)
    val actual = ujson.read(CollectionReadProfileJson.json(p))
    val legacy = ujson.read(ujson.write(actual))
    require(legacy.obj.remove("postedCollectionReadProgress").contains(ujson.Bool(enabled)))
    val expected = ujson.read(java.nio.file.Files.readString(java.nio.file.Path.of(args(2))))
    require(legacy == expected("core"))
    require(expected("geometry")("cache")("independentDemandAdmission") ==
        ujson.Bool(CollectionReadProfileV2.config.independentDemandAdmission))
    require(ujson.read(CollectionReadProfileJson.json(CollectionReadProfileV2.config)) == expected("profile"))
    for (key <- Seq("shadowEarlyProofBind", "proofBankQuiesceIntent", "proofOwnerStateCleanup",
        "factorPreparedStorePool", "projectedRequestHead", "registeredMemoryPreparationDescriptor",
        "backendNaturalAlignedPmp")) require(expected("featureFlags")(key) == ujson.Bool(true))
    require(expected("featureFlags")("preselectRedirectTokenMatches") == ujson.Bool(false))
    java.nio.file.Files.writeString(out.resolve("actual-core.json"), ujson.write(actual, indent=2)+"\n")
    java.nio.file.Files.writeString(out.resolve("CollectionReadBackendGsim.fir"),
        ChiselStage.emitCHIRRTL(new CollectionReadBackendGsim(enabled)))
}
