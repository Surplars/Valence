package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

/** Passive transport view. The host derives store intent from raw instructions,
  * binds it to the rename token, and only then compares these DUT observations.
  */
class PostedCpuBoundary(c: PostedStoreMergeConfig) extends Bundle {
    val valid = Bool()
    val ready = Bool()
    val request = new DataRequest
    val proof = Valid(new PostedStoreProof(c))
    val responseValid = Bool()
    val responseReady = Bool()
    val response = new DataResponse
}

/** Real CPU/LSU/FIFO/StoreBuffer/translation/router path, external cache contract.
  * The host's busy/episode inputs retain a downstream obligation AFTER an actual
  * checked request acceptance and response. No cache SRAM/home/TileLink ownership
  * claim is made by this fixture. No internal control or proof bit is driven.
  */
class PostedStoreCpuLineageGsim(enabled: Boolean) extends Module {
    val profile = FpgaNextConfig.Selected.copy(dataTranslationEntries = 16,
        virtualRamLoadPrecheck = true, preparedStoreLookahead = true,
        storeNextLinePrefetch = true, storePrefetchMruInsertion = true,
        lsuEntries = 4, physicalLoadIngressFlow = true, loadOrderOlderRetire = true,
        fetchPreviousPacket = true)
    val p = profile.coreParams.copy(postedStoreMerge = enabled, fastBufferedStoreRetire = false)
    val c = PostedStoreMergeConfig(tokenIndexBits = p.robBits, tokenTagBits = p.tagBits)
    require(p.renameWidth == 2 && p.commitWidth == 2 && p.robEntries == 16 && p.registeredMemoryRequests &&
        p.bufferedRamStores && p.registeredFetchPacket && !p.fastBufferedStoreRetire &&
        !p.precheckedDataRequestFlow, "ordinary selected CPU lineage fixture geometry changed")
    require(p.memoryEntries == 4 && p.physicalLoadIngressFlow && p.loadOrderOlderRetire && p.fetchPreviousPacket,
        "CPU lineage fixture must retain the selected high-performance memory/frontend configuration")
    val io = IO(new Bundle {
        val instruction0 = Input(Valid(UInt(32.W)))
        val instruction1 = Input(Valid(UInt(32.W)))
        val commitEnable = Input(Bool())
        val externalBusy = Input(Bool())
        val episodeActive = Input(Bool())
        val memory = new DataPort
        val pte = new SvPteReadPort
        val nextFetchPc = Output(UInt(64.W))
        val commit0 = Output(Valid(new CommitRecord(p)))
        val commit1 = Output(Valid(new CommitRecord(p)))
        val rename0 = Output(Valid(new RobToken(p)))
        val rename1 = Output(Valid(new RobToken(p)))
        val renamePc0 = Output(UInt(64.W))
        val renamePc1 = Output(UInt(64.W))
        val renameInstruction0 = Output(UInt(32.W))
        val renameInstruction1 = Output(UInt(32.W))
        val headValid = Output(Bool())
        val headToken = Output(new RobToken(p))
        val headPc = Output(UInt(64.W))
        val headInstruction = Output(UInt(32.W))
        val startValid = Output(Bool())
        val startReady = Output(Bool())
        val start = Output(new MemoryOperation(p))
        val requestOwner = Output(Valid(new RobToken(p)))
        val completionValid = Output(Bool())
        val completionReady = Output(Bool())
        val completion = Output(new BackendCompletion(p))
        val pmpDenied = Output(Bool())
        val dataPrivilege = Output(UInt(2.W))
        val systemStart = Output(Bool())
        val contextEpoch = Output(UInt(32.W))
        val seal = Output(Bool())
        val endEpisode = Output(Bool())
        val busy = Output(Bool())
        val idle = Output(Bool())
        val trap = Output(Valid(new HeadException(p)))
        val redirect = Output(Valid(new FrontendRedirect(p)))
        val recovering = Output(Bool())
        val vm = Output(new VmCsrState)
        val lsu = Output(new PostedCpuBoundary(c))
        val storeIn = Output(new PostedCpuBoundary(c))
        val storeOut = Output(new PostedCpuBoundary(c))
        val backend = Output(new PostedCpuBoundary(c))
        val translated = Output(new PostedCpuBoundary(c))
        val checked = Output(new PostedCpuBoundary(c))
        val physical = Output(new PostedCpuBoundary(c))
    })
    val mapped = Module(new MappedMachineCore(p, dataTranslation = true,
        stagedMemoryFabric = true, bufferTranslatedResponses = true))
    val translation = Module(new SvTranslationService(3, profile.dataTranslationEntries,
        p.pmpEntries, loadPeek = true))
    val backend = mapped.core.core.backend
    val adapter = mapped.observationTranslation.get
    val stores = backend.observationStores.get
    mapped.io.instructions(0) := io.instruction0
    mapped.io.instructions(1) := io.instruction1
    mapped.io.instructionFaults := VecInit(Seq.fill(p.renameWidth)(false.B))
    mapped.io.instructionPageFaults := VecInit(Seq.fill(p.renameWidth)(false.B))
    mapped.io.instructionFaultAddresses.foreach(_ := VecInit(Seq.fill(p.renameWidth)(0.U(64.W))))
    mapped.io.commitEnable := io.commitEnable
    mapped.io.timerInterrupt := false.B
    mapped.io.timeValue := 0.U
    mapped.io.sources := 0.U
    mapped.io.inspectRegister := 0.U
    mapped.io.fetchQuiescent.get := true.B
    mapped.io.fenceIFlushReady := true.B
    mapped.io.externalPrefetchBusy.foreach(_ := false.B)
    mapped.io.vmFlushReady.get := translation.io.idle && BoringUtils.bore(adapter.io.idle)
    val flush = mapped.io.vmFlush.get && mapped.io.vmFlushReady.get
    translation.io.flush := flush
    mapped.io.precheckFlush.get := flush
    translation.io.pmpState := mapped.io.pmpState.get
    translation.io.client <> mapped.io.translation.get
    translation.io.loadPeek.get <> mapped.io.translationPeek.get
    io.pte <> translation.io.memory
    io.memory <> mapped.io.memory
    mapped.io.posted.foreach { posted =>
        posted.busy := io.externalBusy
        posted.episodeActive := io.episodeActive
    }
    io.nextFetchPc := BoringUtils.bore(mapped.core.core.io.nextFetchPc.get)
    io.commit0 := mapped.io.commit(0)
    io.commit1 := mapped.io.commit(1)
    for ((token, pc, instruction, lane) <- Seq(
        (io.rename0, io.renamePc0, io.renameInstruction0, 0),
        (io.rename1, io.renamePc1, io.renameInstruction1, 1))) {
        token.valid := BoringUtils.bore(backend.io.renamed(lane).valid)
        token.bits := BoringUtils.bore(backend.io.renamed(lane).bits.token)
        pc := BoringUtils.bore(backend.io.allocate(lane).bits.rename.pc)
        instruction := BoringUtils.bore(backend.io.allocate(lane).bits.rename.instruction)
    }
    io.headValid := BoringUtils.bore(backend.ledger.io.headValid)
    io.headToken := BoringUtils.bore(backend.headRenamed.token)
    io.headPc := BoringUtils.bore(backend.headRequest.rename.pc)
    io.headInstruction := BoringUtils.bore(backend.headRequest.rename.instruction)
    io.startValid := BoringUtils.bore(backend.lsu.io.start.valid)
    io.startReady := BoringUtils.bore(backend.lsu.io.start.ready)
    io.start := BoringUtils.bore(backend.lsu.io.start.bits)
    io.requestOwner := BoringUtils.bore(backend.lsu.io.requestOwner)
    io.completionValid := BoringUtils.bore(backend.lsu.io.complete.valid)
    io.completionReady := BoringUtils.bore(backend.lsu.io.complete.ready)
    io.completion := BoringUtils.bore(backend.lsu.io.complete.bits)
    io.pmpDenied := BoringUtils.bore(backend.pmpCheck.io.denied)
    io.dataPrivilege := BoringUtils.bore(backend.dataPrivilege)
    io.systemStart := BoringUtils.bore(backend.systemStart)
    io.contextEpoch := mapped.io.posted.map(_.contextEpoch).getOrElse(0.U)
    io.seal := mapped.io.posted.map(_.seal).getOrElse(false.B)
    io.endEpisode := mapped.io.posted.map(_.endEpisode).getOrElse(false.B)
    io.busy := mapped.io.memoryBusy
    io.idle := !mapped.io.memoryBusy && mapped.io.robOccupancy === 0.U &&
        BoringUtils.bore(adapter.io.idle) && translation.io.idle
    io.trap := mapped.io.trap
    io.redirect := mapped.io.redirect
    io.recovering := mapped.io.recovering
    io.vm := mapped.io.vmState.get
    def observe(out: PostedCpuBoundary, port: DataPort,
        proof: Option[ValidIO[PostedStoreProof]]): Unit = {
        out.valid := BoringUtils.bore(port.request.valid)
        out.ready := BoringUtils.bore(port.request.ready)
        out.request := BoringUtils.bore(port.request.bits)
        out.proof := proof.map(BoringUtils.bore(_)).getOrElse(0.U.asTypeOf(Valid(new PostedStoreProof(c))))
        out.responseValid := BoringUtils.bore(port.response.valid)
        out.responseReady := BoringUtils.bore(port.response.ready)
        out.response := BoringUtils.bore(port.response.bits)
    }
    observe(io.lsu, backend.lsu.io.memory, backend.lsu.io.postedProof)
    observe(io.storeIn, stores.io.upstream, stores.io.upstreamProof)
    observe(io.storeOut, stores.io.memory, stores.io.memoryProof)
    observe(io.backend, backend.io.memory, backend.io.posted.map(_.requestProof))
    observe(io.translated, adapter.io.virtual, adapter.io.posted.map(_.upstreamProof))
    observe(io.checked, adapter.io.physical, adapter.io.posted.map(_.requestProof))
    observe(io.physical, mapped.io.memory, mapped.io.posted.map(_.requestProof))
}

object PostedStoreCpuLineageGsimMain extends App {
    require(args.length == 2 && Set("on", "off").contains(args(1)), "target directory and explicit on/off required")
    ChiselStage.emitCHIRRTLFile(new PostedStoreCpuLineageGsim(args(1) == "on"), Array("--target-dir", args(0)))
}
