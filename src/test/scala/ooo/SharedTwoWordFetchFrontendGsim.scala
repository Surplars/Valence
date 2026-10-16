package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Real same-configuration OFF/ON frontends; software independently owns memory and cache expectations. */
class SharedTwoWordFetchFrontendGsim(val p: OooParams) extends Module {
    val io = IO(new Bundle {
        val pairMismatch = Input(Bool())
        val pc = Input(UInt(64.W))
        val requestFrontier = Input(UInt(64.W))
        val suppressRequest = Input(Bool())
        val enable = Input(Bool())
        val invalidate = Input(Bool())
        val pause = Input(Bool())
        val privilege = Input(UInt(2.W))
        val virtualized = Input(Bool())
        val pmpCfg0 = Input(UInt(8.W))
        val pmpAddr0 = Input(UInt(54.W))
        val requestReady = Input(Bool())
        val requestValid = Output(Bool())
        val requestAddress = Output(UInt(64.W))
        val requestMask = Output(UInt(2.W))
        val responseValid = Input(Bool())
        val responseData = Input(UInt(64.W))
        val responseErrors = Input(UInt(2.W))
        val responsePages = Input(UInt(2.W))
        val responseReady = Output(Bool())
        val quiescent = Output(Bool())
        val lane0 = Output(Valid(UInt(32.W)))
        val lane1 = Output(Valid(UInt(32.W)))
        val errors = Output(UInt(2.W))
        val pages = Output(UInt(2.W))
        val fault0 = Output(UInt(64.W))
        val fault1 = Output(UInt(64.W))
        val faultOffset0 = Output(UInt(5.W))
        val faultOffset1 = Output(UInt(5.W))
    })

    val qualifiedCompactKeys = p.frontendCacheSets == 16 && p.renameWidth == 2 && p.pmpEntries == 16 &&
        p.compressedInstructions && p.stableFetchFaultMetadata && p.alignedFetchPmp && p.rawFetchPresence &&
        p.parallelFetchTagLookup && p.parallelFetchAlignment && p.registeredFetchWindow &&
        p.independentFetchPayloadCapture && p.fetchPreviousPacket && p.alignedFetchPermissionStage &&
        p.fetchAddressBeforePmp
    require(qualifiedCompactKeys, "this bounded check requires the current 16-set native frontend tuple")
    def configuration(enabled: Boolean): Map[String, Any] = Map(
        "pmpEntries" -> 16, "compressed" -> p.compressedInstructions, "cacheSets" -> p.frontendCacheSets,
        "fetchWidth" -> p.renameWidth, "stableFaultMetadata" -> p.stableFetchFaultMetadata,
        "alignedFetchPmp" -> p.alignedFetchPmp, "rawFetchPresence" -> p.rawFetchPresence,
        "parallelFetchTagLookup" -> p.parallelFetchTagLookup, "parallelAlignment" -> p.parallelFetchAlignment,
        "registeredWindow" -> p.registeredFetchWindow, "independentPayloadCapture" -> p.independentFetchPayloadCapture,
        "fetchPreviousPacket" -> p.fetchPreviousPacket, "boundedRequestFrontier" -> p.alignedFetchPermissionStage,
        "fetchAddressBeforePmp" -> p.fetchAddressBeforePmp, "compactCacheKeys" -> qualifiedCompactKeys,
        "sharedTwoWordFetchPmp" -> enabled)
    def build(enabled: Boolean): SynchronousFetch = Module(new SynchronousFetch(
        pmpEntries = 16, compressed = p.compressedInstructions, cacheSets = p.frontendCacheSets,
        fetchWidth = p.renameWidth, stableFaultMetadata = p.stableFetchFaultMetadata,
        alignedFetchPmp = p.alignedFetchPmp, rawFetchPresence = p.rawFetchPresence,
        parallelFetchTagLookup = p.parallelFetchTagLookup, parallelAlignment = p.parallelFetchAlignment,
        registeredWindow = p.registeredFetchWindow, independentPayloadCapture = p.independentFetchPayloadCapture,
        fetchPreviousPacket = p.fetchPreviousPacket, boundedRequestFrontier = p.alignedFetchPermissionStage,
        fetchAddressBeforePmp = p.fetchAddressBeforePmp, compactCacheKeys = qualifiedCompactKeys,
        sharedTwoWordFetchPmp = enabled))
    val candidate = build(true)
    val reference = build(false)
    if (p.alignedFetchPermissionStage) {
        candidate.io.requestFrontier.get := io.requestFrontier
        candidate.io.suppressRequest.get := io.suppressRequest
        reference.io.requestFrontier.get := io.requestFrontier
        reference.io.suppressRequest.get := io.suppressRequest
    }
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := io.pmpCfg0
    pmp.addr(0) := io.pmpAddr0
    PmpState.decodeRegions(pmp)
    candidate.io.pc := io.pc
    candidate.io.enable := io.enable
    candidate.io.invalidate := io.invalidate
    candidate.io.pause := io.pause
    candidate.io.privilege := io.privilege
    candidate.io.virtualized := io.virtualized
    candidate.io.pmpState := pmp
    candidate.io.memory.request.ready := io.requestReady
    candidate.io.memory.response.valid := io.responseValid
    candidate.io.memory.response.bits := io.responseData
    candidate.io.memory.responseError := io.responseErrors
    candidate.io.memory.responsePageFault := io.responsePages
    reference.io.pc := io.pc
    reference.io.enable := io.enable
    reference.io.invalidate := io.invalidate
    reference.io.pause := io.pause
    reference.io.privilege := io.privilege
    reference.io.virtualized := io.virtualized
    reference.io.pmpState := pmp
    reference.io.memory.request.ready := io.requestReady
    reference.io.memory.response.valid := io.responseValid
    reference.io.memory.response.bits := io.responseData
    reference.io.memory.responseError := io.responseErrors
    reference.io.memory.responsePageFault := io.responsePages
    io.requestValid := candidate.io.memory.request.valid
    io.requestAddress := candidate.io.memory.request.bits
    io.requestMask := candidate.io.memory.requestMask
    io.responseReady := candidate.io.memory.response.ready
    io.quiescent := candidate.io.quiescent
    io.lane0 := candidate.io.instructions(0)
    io.lane1 := candidate.io.instructions(1)
    io.errors := candidate.io.instructionFaults.asUInt
    io.pages := candidate.io.instructionPageFaults.asUInt
    io.fault0 := candidate.io.instructionFaultAddresses(0)
    io.fault1 := candidate.io.instructionFaultAddresses(1)
    io.faultOffset0 := candidate.io.instructionFaultOffsets(0)
    io.faultOffset1 := candidate.io.instructionFaultOffsets(1)

    // Compare implementation bits, including deterministic dead payload; the independent
    // software oracle compares only valid architectural payload and offered transactions.
    assert(candidate.io.asUInt === (reference.io.asUInt ^ io.pairMismatch.asUInt),
        "shared two-word frontend full IO mismatch")
}

object SharedTwoWordFetchFrontendGsimMain extends App {
    require(args.length == 2, "output directory and experimental board experiment.json required")
    val out = Paths.get(args(0))
    val board = ujson.read(Files.readString(Paths.get(args(1))))
    val c = ThreeProofRowNativeProfile.config
    val p = c.coreParams
    def json(x: Any): ujson.Value = ujson.read(PostedBoardConfiguration.json(x))
    require(board("schema").str == "experimental-shared-two-word-fetch-pmp-board-v1")
    val order = ujson.Obj("core" -> ujson.Arr.from(p.productElementNames),
        "profile" -> ujson.Arr.from(c.productElementNames))
    require(p.productArity == 178 && c.productArity == 95)
    require(board("core") == json(p) && board("profile") == json(c) && board("fieldOrder") == order)
    var built: Option[SharedTwoWordFetchFrontendGsim] = None
    ChiselStage.emitCHIRRTLFile({ val dut = new SharedTwoWordFetchFrontendGsim(p); built = Some(dut); dut },
        Array("--target-dir", out.toString))
    val dut = built.get
    // Read every actual retained constructor field, rejecting missing/ambiguous witnesses.
    def actual(frontend: SynchronousFetch, expected: Map[String, Any]): Map[String, Any] = expected.map {
        case (name, value) =>
            val fields = classOf[SynchronousFetch].getDeclaredFields.filter(f =>
                f.getName == name || f.getName.endsWith("$$" + name))
            require(fields.length == 1, "missing/ambiguous actual frontend parameter: " + name)
            fields.head.setAccessible(true)
            val observed = fields.head.get(frontend)
            require(observed == value, "actual frontend constructor differs: " + name)
            name -> observed
    }
    val off = actual(dut.reference, dut.configuration(false))
    val on = actual(dut.candidate, dut.configuration(true))
    require(dut.reference.io.memory.requestMask.getWidth == 2 && dut.candidate.io.memory.requestMask.getWidth == 2)
    Files.writeString(out.resolve("experimental-frontend-config.json"), ujson.Obj(
        "schema" -> "experimental-shared-two-word-frontend-pair-v1",
        "core" -> json(p), "profile" -> json(c), "fieldOrder" -> order,
        "actualOffFrontend" -> json(off), "actualOnFrontend" -> json(on),
        "configurationBinding" -> "core/profile/order matched to export; all 16 actual constructor fields match selected native MachinePlatform definition",
        "comparison" -> "full same-input real OFF/ON frontend IO each cycle; dead payload only implementation equivalence",
        "wholeBoardQualified" -> false, "physicalQualification" -> false).render(indent = 2) + "\n")
}
