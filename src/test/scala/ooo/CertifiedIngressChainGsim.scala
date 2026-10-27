package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._
import soc.platform.CommonA1RebuildProfile

/** Actual integer/FP consumers, registered request queue, StoreBuffer, DTA,
  * Sv39 translation service and AtomicMemory. Host supplies only backing/PTE replies.
  * All observation ports are passive; the independent host owns transaction obligations.
  */
class CertifiedIngressChainGsim(enabled: Boolean, profileOverride: Option[String] = None) extends Module {
    val config = profileOverride.map(CommonA1RebuildProfile.named).getOrElse(
        if (enabled) CommonA1RebuildProfile.FullR1M3CertifiedIngress
        else CommonA1RebuildProfile.FullR1M3AdvisoryOwner).config
    val p = config.coreParams
    require(p.memoryEntries == 4 && p.tagBits == 64 && p.robEntries == 16)
    require(p.registeredMemoryRequests && p.registeredStoreResponseOwners && !p.registeredLocalStoreResponses)
    require(!p.taggedStoreReturns && !p.fastHeadLoadRetire && !p.registeredLoadResultReady)
    val io = IO(new Bundle {
        val start = Flipped(Decoupled(new BufferedReturnOperation(p)))
        val useCertificate = Input(Bool())
        val proofValid = Output(Bool())
        val proofAllowed = Output(Bool())
        val proofAddress = Output(UInt(64.W))
        val finalRequest = Output(Bool())
        val finalPayload = Output(new DataRequest)
        val finalOrigin = Output(Bool())
        val selectedSource = Output(UInt(3.W))
        val certifiedPass = Output(Bool())
        val certifiedNominal = Output(Bool())
        val ingressPush = Output(Bool())
        val checkedPush = Output(Bool())
        val checkedPayload = Output(new DataRequest)
        val checkedFault = Output(Bool())
        val parallel = Input(Bool())
        val cancel = Input(UInt(4.W))
        val complete = Decoupled(new BackendCompletion(p))
        val startSlots = Output(UInt(4.W))
        val live = Output(UInt(4.W))
        val discarded = Output(Bool())
        val requestOwned = Output(Bool())
        val requestToken = Output(new RobToken(p))
        val integerReply = Output(Bool())
        val fastStore = Flipped(Decoupled(new DataRequest))
        val fpMode = Input(Bool())
        // Scalar command avoids exposing the simulator's top-level Vec accessor ABI.
        val fpValid = Input(Bool())
        val fpReady = Output(Bool())
        val fpToken = Input(new RobToken(p))
        val fpInstruction = Input(UInt(32.W))
        val fpAddress = Input(UInt(64.W))
        val fpData = Input(UInt(64.W))
        val fpPc = Input(UInt(64.W))
        val fpComplete = Decoupled(new BackendCompletion(p))
        val fpBusy = Output(Bool())
        val vm = Input(new VmCsrState)
        val pmpCfg = Input(UInt(8.W)); val pmpAddress = Input(UInt(54.W))
        val flush = Input(Bool()); val clearReservation = Input(Bool())
        val pte = new SvPteReadPort
        val epoch = Output(UInt(32.W)); val stable = Output(Bool())
        val ownerCount = Output(UInt(3.W)); val ownerHeadValid = Output(Bool())
        val ownerHead = Output(UInt(2.W)); val requestSlot = Output(UInt(2.W))
        val phases = Output(UInt(8.W))
        val slotRequestValid = Output(UInt(4.W)); val slotStartReady = Output(UInt(4.W))
        val slotResponseValid = Output(UInt(4.W)); val slotResponseReady = Output(UInt(4.W))
        val slotCompleteValid = Output(UInt(4.W)); val slotDiscard = Output(UInt(4.W))
        val slotOwner0 = Output(new RobToken(p)); val slotOwner1 = Output(new RobToken(p))
        val slotOwner2 = Output(new RobToken(p)); val slotOwner3 = Output(new RobToken(p))
        val translatedRequest = Output(Bool()); val translated = Output(new DataRequest)
        val translatedResponse = Output(Bool())
        val atomicPhase = Output(UInt(3.W))
        val memory = new DataPort
        val integerBusy = Output(Bool())
        val bufferIdle = Output(Bool())
        val allIdle = Output(Bool())
    })
    val lsu = Module(new ParallelLoadStoreUnit(p))
    val requests = Module(new RegisteredRequestQueue(p))
    val stores = Module(new StoreBuffer(p))
    val responses = Module(new DataResponseBuffer(registerPayload = true, registerHead = true, emptyFlow = true))
    val certified = WireDefault(false.B)
    lsu.io.start.valid := io.start.valid && (!io.useCertificate || certified)
    io.start.ready := lsu.io.start.ready && (!io.useCertificate || certified)
    lsu.io.start.bits := 0.U.asTypeOf(new MemoryOperation(p))
    for ((name, field) <- io.start.bits.elements) { lsu.io.start.bits.elements(name) := field }
    lsu.io.parallel := io.parallel
    lsu.io.cancel := VecInit((0 until 4).map(i => io.cancel(i)))
    lsu.io.fastStoreRetire := false.B
    lsu.io.fastLoadRetire := false.B
    lsu.io.issueDestination.foreach(_ := 0.U.asTypeOf(Valid(UInt(p.physBits.W))))
    lsu.io.relaxStoreOwner.foreach(_ := 0.U.asTypeOf(Valid(new RobToken(p))))
    lsu.io.boundHeadStoreOverlapQualified.foreach(_ := false.B)
    lsu.io.candidateAdmission.foreach { admission =>
        admission.precheckedLoad := false.B
        admission.parallel := io.parallel
    }
    io.complete <> lsu.io.complete
    requests.io.enq <> lsu.io.memory.request
    stores.io.upstream.request <> requests.io.deq
    stores.io.upstream.request.bits.size := Mux(requests.io.deq.valid, requests.io.deq.bits.size, 0.U)
    stores.io.upstream.response <> lsu.io.memory.response
    requests.proofIn.foreach(_ := lsu.io.postedProof.get)
    stores.io.upstreamProof.foreach(_ := requests.proofOut.get)
    requests.canonicalOriginIn.foreach(_ := lsu.io.canonicalStoreOrigin.get)
    stores.io.upstreamCanonicalStoreOrigin.foreach(_ := requests.canonicalOriginOut.get)
    requests.frozenProofIn.foreach(_ := lsu.io.frozenStoreProof.get)
    stores.io.upstreamFrozenStoreProof.foreach(_ := requests.frozenProofOut.get)
    stores.io.fastProof.foreach(_ := 0.U.asTypeOf(stores.io.fastProof.get))
    stores.io.externalPostedBusy.foreach(_ := false.B)
    stores.io.fastStore <> io.fastStore
    io.startSlots := VecInit(lsu.slots.map(slot =>
        BoringUtils.bore(slot.io.start.valid) && BoringUtils.bore(slot.io.start.ready))).asUInt
    io.live := lsu.io.live.asUInt
    io.discarded := lsu.io.discarded
    io.requestOwned := lsu.io.memory.request.fire
    io.requestToken := lsu.io.requestOwner.bits
    io.integerReply := lsu.io.memory.response.fire
    io.integerBusy := lsu.io.busy || stores.io.busy || requests.io.count =/= 0.U

    val fp = Module(new FloatingPointMemoryPipeline(p))
    fp.io.execute.valid := io.fpValid && io.fpMode
    fp.io.execute.bits := 0.U.asTypeOf(new FloatingPointExecution(p))
    fp.io.execute.bits.command.token := io.fpToken
    fp.io.execute.bits.command.instruction := io.fpInstruction
    fp.io.execute.bits.command.integerSource := io.fpAddress
    fp.io.execute.bits.operands(1) := io.fpData
    fp.io.pc := io.fpPc
    fp.io.trap := false.B
    fp.io.pmpState := 0.U.asTypeOf(new PmpState)
    fp.io.dataPrivilege := 3.U
    fp.io.virtualized := false.B
    io.fpReady := fp.io.execute.ready && io.fpMode
    io.fpComplete <> fp.io.complete
    io.fpBusy := fp.io.busy
    responses.io.upstream.request.valid := Mux(io.fpMode, fp.io.memory.request.valid, stores.io.memory.request.valid)
    responses.io.upstream.request.bits := Mux(io.fpMode, fp.io.memory.request.bits, stores.io.memory.request.bits)
    fp.io.memory.request.ready := io.fpMode && responses.io.upstream.request.ready
    stores.io.memory.request.ready := !io.fpMode && responses.io.upstream.request.ready
    fp.io.memory.response.valid := io.fpMode && responses.io.upstream.response.valid
    fp.io.memory.response.bits := responses.io.upstream.response.bits
    stores.io.memory.response.valid := !io.fpMode && responses.io.upstream.response.valid
    stores.io.memory.response.bits := responses.io.upstream.response.bits
    responses.io.upstream.response.ready := Mux(io.fpMode, fp.io.memory.response.ready, stores.io.memory.response.ready)
    val adapter = Module(new DataTranslationAdapter(p, registerCheckedRequests = true,
        translationHitFlow = config.translationHitFlow,
        registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent,
        queuedHeadSelection = p.queuedHeadSelection, alignedNextLinePmp = p.alignedNextLinePmp,
        factorCheckedNextAllowed = p.factorCheckedNextAllowed, certifiedLoadIngress = p.certifiedLoadIngress))
    val translation = Module(new SvTranslationService(p.virtualMemoryLevels, config.dataTranslationEntries,
        p.pmpEntries, loadPeek = true, writeReadReuse = config.dataTlbWriteReadReuse,
        decodedNaturalPmp = p.decodedNaturalPmp))
    val atomic = Module(new AtomicDataMemory(p.speculativeRamBase, p.speculativeRamBytes,
        registerResponseOwners = true))
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := io.pmpCfg; pmp.addr(0) := io.pmpAddress
    PmpState.decodeRegions(pmp)
    adapter.io.virtual <> responses.io.downstream
    adapter.io.vmState := io.vm; adapter.io.pmpState := pmp
    adapter.io.canonicalStoreOrigin.foreach { origin =>
        origin := stores.io.memoryCanonicalStoreOrigin.get
        origin.valid := responses.io.upstream.request.valid && !io.fpMode && stores.io.memoryCanonicalStoreOrigin.get.valid
    }
    adapter.io.frozenStoreProof.foreach(_ := stores.io.memoryFrozenStoreProof.get)
    translation.io.pmpState := pmp
    translation.io.client <> adapter.io.translation
    translation.io.loadPeek.get <> adapter.io.translationPeek.get
    adapter.io.precheckFlush.get := io.flush; translation.io.flush := io.flush
    val preparation = Module(new BufferedVirtualRamLoadPreparation(p))
    preparation.io.current.valid := io.start.valid && io.useCertificate
    preparation.io.current.bits.token := io.start.bits.token
    preparation.io.current.bits.address := io.start.bits.address
    preparation.io.current.bits.size := io.start.bits.size
    preparation.io.lookahead := 0.U.asTypeOf(preparation.io.lookahead)
    preparation.io.descriptorOwnerLive := VecInit(Seq.fill(2)(true.B))
    preparation.io.translatedOwnerLive := true.B
    preparation.io.preparedOwnerLive := VecInit(Seq.fill(2)(true.B))
    preparation.io.issued.valid := lsu.io.start.fire
    preparation.io.issued.bits := io.start.bits.token
    preparation.io.precheck <> adapter.io.loadPrecheck.get
    preparation.io.pmpState := pmp
    preparation.io.privilege := io.vm.dataPrivilege
    preparation.io.flush := io.flush
    val proof = preparation.io.prepared
    certified := proof.valid && proof.bits.allowed && proof.bits.token.asUInt === io.start.bits.token.asUInt &&
        proof.bits.address === io.start.bits.address && proof.bits.size === io.start.bits.size &&
        proof.bits.epoch === adapter.io.loadPrecheck.get.epoch
    when(io.useCertificate) {
        lsu.io.start.bits.precheckedLoad := certified
        lsu.io.start.bits.physicalAddress := proof.bits.physicalAddress
        lsu.io.start.bits.translationEpoch := proof.bits.epoch
    }
    io.proofValid := proof.valid
    io.proofAllowed := proof.valid && proof.bits.allowed
    io.proofAddress := proof.bits.physicalAddress
    io.finalRequest := adapter.io.virtual.request.fire
    io.finalPayload := adapter.io.virtual.request.bits
    io.finalOrigin := adapter.io.canonicalStoreOrigin.get.valid
    io.selectedSource := Mux(io.fpMode, 4.U, Mux(BoringUtils.bore(stores.drainRequest), 1.U,
        Mux(BoringUtils.bore(stores.flowFastWrite), 2.U, Mux(BoringUtils.bore(stores.flowBufferedWrite), 3.U, 0.U))))
    io.certifiedPass := (if (enabled) BoringUtils.bore(adapter.certifiedIngressPass) else false.B)
    io.certifiedNominal := (if (enabled) BoringUtils.bore(adapter.certifiedIngressNominal) else false.B)
    io.ingressPush := BoringUtils.bore(adapter.virtualRequests.get.io.enq.valid) &&
        BoringUtils.bore(adapter.virtualRequests.get.io.enq.ready)
    io.checkedPush := BoringUtils.bore(adapter.checked.get.enq.valid) &&
        BoringUtils.bore(adapter.checked.get.enq.ready)
    io.checkedPayload := BoringUtils.bore(adapter.checked.get.enq.bits.request)
    io.checkedFault := BoringUtils.bore(adapter.checked.get.enq.bits.fault)
    io.pte <> translation.io.memory
    io.epoch := adapter.io.loadPrecheck.get.epoch
    io.stable := adapter.io.loadPrecheck.get.stable
    atomic.io.cpu <> adapter.io.physical
    atomic.io.dma.request.valid := false.B
    atomic.io.dma.request.bits := 0.U.asTypeOf(new DataRequest)
    atomic.io.dma.response.ready := true.B
    atomic.io.clearReservation := io.clearReservation
    io.memory <> atomic.io.memory
    io.translatedRequest := adapter.io.physical.request.fire
    io.translated := adapter.io.physical.request.bits
    io.translatedResponse := adapter.io.physical.response.fire
    io.atomicPhase := BoringUtils.bore(atomic.unit.state)
    io.ownerCount := BoringUtils.bore(lsu.owners.io.count)
    io.ownerHeadValid := BoringUtils.bore(lsu.owners.io.deq.valid)
    io.ownerHead := BoringUtils.bore(lsu.owners.io.deq.bits)
    io.requestSlot := BoringUtils.bore(lsu.owners.io.enq.bits)
    io.phases := Cat(lsu.slots.reverse.map(slot => BoringUtils.bore(slot.io.phase)))
    io.slotRequestValid := VecInit(lsu.slots.map(slot => BoringUtils.bore(slot.io.memory.request.valid))).asUInt
    io.slotStartReady := VecInit(lsu.slots.map(slot => BoringUtils.bore(slot.io.start.ready))).asUInt
    io.slotResponseValid := VecInit(lsu.slots.map(slot => BoringUtils.bore(slot.io.memory.response.valid))).asUInt
    io.slotResponseReady := VecInit(lsu.slots.map(slot => BoringUtils.bore(slot.io.memory.response.ready))).asUInt
    io.slotCompleteValid := VecInit(lsu.slots.map(slot => BoringUtils.bore(slot.io.complete.valid))).asUInt
    io.slotDiscard := VecInit(lsu.slots.map(slot => BoringUtils.bore(slot.io.discarded))).asUInt
    Seq(io.slotOwner0, io.slotOwner1, io.slotOwner2, io.slotOwner3).zipWithIndex.foreach {
        case (out, i) => out := lsu.io.owner(i)
    }
    io.bufferIdle := responses.io.idle
    io.allIdle := !io.integerBusy && !fp.io.busy && responses.io.idle && adapter.io.idle && translation.io.idle && io.atomicPhase === 0.U
    when(io.start.valid) {
        assert(!io.start.bits.precheckedLoad, "host cannot inject certified authority")
        when(io.useCertificate) {
            assert(io.start.bits.virtualized && !io.start.bits.store && !io.start.bits.atomic,
                "actual preparation is restricted to ordinary virtual loads")
        }
    }
    when(io.fpMode) { assert(!io.integerBusy && !io.start.valid && !io.fastStore.valid) }
    val previousMode = RegNext(io.fpMode, false.B)
    when(previousMode =/= io.fpMode) { assert(io.allIdle, "test domain changes require complete consumer drain") }
}

object CertifiedIngressChainGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)))
    ChiselStage.emitCHIRRTLFile(new CertifiedIngressChainGsim(args(1) == "1"), Array("--target-dir", args(0)))
}
