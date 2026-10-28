package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Exact candidate77 core params, actual decoded backend and translation.
  * Direct ordered tagged physical responder, no cache/Home/board qualification.
  */
class ReadyStoreQuery77BackendGsim(queryEnabled: Boolean, proofRows: Int = 2,
    preselectRedirectTokenMatches: Boolean = false, shadowEarlyProofBind: Boolean = false,
    proofControlInputs: Boolean = false, proofBankQuiesceIntent: Boolean = false,
    proofBankOwnerCleanup: Boolean = false, factorPreparedStorePool: Boolean = false,
    currentProfile: Option[FpgaNextConfig] = None, projectedRequestHead: Boolean = false,
    registeredMemoryPreparationDescriptor: Boolean = false, earlyLoadPreparationDescriptor: Boolean = false, backendNaturalAlignedPmp: Boolean = false, virtualStoreOperandLookahead: Boolean = false, bankedStoreData: Boolean = false) extends Module {
    require(Set(2, 3).contains(proofRows) && (proofRows != 3 || queryEnabled))
    val profile = currentProfile.getOrElse(if (proofRows == 3) ThreeProofRowCandidateProfile.candidate
        else ReadyStoreQuery77Profile.select(queryEnabled))
    val p = profile.coreParams
    private val enabled = true
    private val overlap = true
    private val enabledProof = true
    private val earlyCredits = 2
    private val memoryEntries = 4
    require(if (currentProfile.nonEmpty) p.productArity == 179 && profile.productArity == 96
        else p.productArity == 178 && profile.productArity == 95)
    require(p.pendingReadyStoreQuery == queryEnabled && p.pendingReadyStoreBypass)
    require(p.registeredPendingStoreQuery && p.memoryPreparationHeadMask && p.registeredIssueHeadMask)
    require(p.pendingVirtualStoreProofSlots == proofRows && p.pendingStoreEarlyLoadCredits == 2)
    require(p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 4 && p.tagBits == 64)
    require(p.taggedStoreReturns && p.postedStoreMerge && p.pmpChangePublicationEnabled)
    require(p.speculativeRamBase == BigInt("80200000", 16) && p.speculativeRamBytes == BigInt("80000000", 16))
    val io = IO(new Bundle {
        val control = if (proofControlInputs) Some(Input(new Bundle {
            val prefetchBusy = Bool()
            val blockNew = Bool()
            val timerInterrupt = Bool()
            val externalInterrupt = Bool()
            val holdFetch = Bool()
        })) else None
        val shadow = if (proofControlInputs) Some(Output(new Bundle {
            val mask = UInt(proofRows.W)
            val actualMask = UInt(proofRows.W)
            val offer = Bool()
            val systemPending = Bool()
            val reserveSystem = Bool()
            val irqDrain = Bool()
            val evict = Bool()
            val slot = UInt(2.W)
        })) else None
        val instruction0 = Input(Valid(UInt(32.W)))
        val instruction1 = Input(Valid(UInt(32.W)))
        val pc0 = Input(UInt(64.W))
        val pc1 = Input(UInt(64.W))
        val decoded0 = Output(new IntegerRequest)
        val decoded1 = Output(new IntegerRequest)
        val storeDataWriteMask = Output(UInt(2.W))
        val poolBare = Output(Bool())
        val poolOriginalMask = Output(UInt(16.W))
        val descriptorValid = Output(Bool())
        val descriptorToken = Output(new RobToken(p))
        val descriptorSaved = Output(Bool())
        val poolStageValid = Output(Bool())
        val poolStageToken = Output(new RobToken(p))
        val poolStageAddress = Output(UInt(64.W))
        val poolStageIndex = Output(UInt(p.robBits.W))
        val poolStageData = Output(UInt(64.W))
        val poolStageSize = Output(UInt(2.W))
        val probeIndex = Input(UInt(4.W))
        val actualQueryEnabled = Output(Bool())
        val actualHead = Output(UInt(4.W))
        val selectedLoadValid = Output(Bool())
        val selectedToken = Output(new RobToken(p))
        val queryEligibleMask = Output(UInt(16.W))
        val queryMask = Output(UInt(16.W))
        val presentOwners = Output(UInt(16.W))
        val bankAdmission = Output(Bool())
        val bankAdmitIndex = Output(UInt(4.W))
        val bankEmpty = Output(UInt(2.W))
        val queryPaused = Output(Bool())
        val queryStable = Output(Bool())
        val creditAvailable = Output(Bool())
        val probeAddressKnown = Output(Bool())
        val probeOwnerValid = Output(Bool())
        val probeOlder = Output(Bool())
        val probeAtHead = Output(Bool())
        val probeDataReady = Output(Bool())
        val probePending = Output(Bool())
        val probeToken = Output(new RobToken(p))
        val proof = Output(Valid(new MemoryAddressProof(p)))
        val proofSecond = Output(Valid(new MemoryAddressProof(p)))
        val proofBoundMask = Output(UInt(proofRows.W))
        val creditActiveMask = Output(UInt(2.W))
        val creditReservedMask = Output(UInt(2.W))
        val creditOwnerSecond = Output(new RobToken(p))
        val b2Accepted = Output(Bool())
        val lsuIdleMask = Output(UInt(4.W))
        val bound = Output(Bool())
        val creditReserved = Output(Bool())
        val creditActive = Output(Bool())
        val creditOwner = Output(new RobToken(p))
        val lsuRequestFire = Output(Bool())
        val lsuRequestOwner = Output(Valid(new RobToken(p)))
        val lsuOffer = Output(Bool())
        val lsuReady = Output(Bool())
        val lsuStore = Output(Bool())
        val lsuFrozen = Output(Valid(new FrozenStoreProof))
        val lsuOwner0 = Output(Valid(new RobToken(p)))
        val lsuOwner1 = Output(Valid(new RobToken(p)))
        val lsuOwner2 = Output(Valid(new RobToken(p)))
        val lsuOwner3 = Output(Valid(new RobToken(p)))
        val upstreamRequest = Output(Valid(new DataRequest(p.dataReturnHandleBits)))
        val upstreamFrozen = Output(Valid(new FrozenStoreProof))
        val queryWrite = Output(Bool())
        val querySize = Output(UInt(3.W))
        val queryPbmt = Output(UInt(2.W))
        val renamed0 = Output(Valid(new RenamedInstruction(p)))
        val renamed1 = Output(Valid(new RenamedInstruction(p)))
        val commit0 = Output(Valid(new CommitRecord(p)))
        val commit1 = Output(Valid(new CommitRecord(p)))
        val issued0 = Output(Valid(new BackendCompletion(p)))
        val issued1 = Output(Valid(new BackendCompletion(p)))
        val commitEnable = Input(Bool())
        val recover = Input(Valid(new RecoveryRequest(p)))
        val recoveryAccepted = Output(Bool())
        val recovering = Output(Bool())
        val occupancy = Output(UInt(p.countBits.W))
        val redirect = Output(Valid(new FrontendRedirect(p))); val trap = Output(Valid(new HeadException(p)))
        val headException = Output(Valid(new HeadException(p)))
        val inspectRegister = Input(UInt(5.W))
        val committedValue = Output(UInt(64.W))
        val physical = new DataPort(p.dataReturnHandleBits)
        val pte = new SvPteReadPort
        val translationHit = Output(Bool())
        val translationWalk = Output(Bool())
        val queryValid = Output(Bool())
        val queryHit = Output(Bool())
        val queryAddress = Output(UInt(64.W))
        val queryPhysical = Output(UInt(64.W))
        val epoch = Output(UInt(32.W))
        val lsuStart = Output(Bool())
        val lsuParallel = Output(Bool())
        val lsuPrechecked = Output(Bool())
        val lsuVa = Output(UInt(64.W))
        val lsuPa = Output(UInt(64.W))
        val lsuToken = Output(new RobToken(p))
        val upstreamFire = Output(Bool())
        val upstreamPrechecked = Output(Bool())
        val upstreamAddress = Output(UInt(64.W))
        val vm = Output(new VmCsrState)
        val idle = Output(Bool())
        val serialStoreOwner = Output(Valid(new RobToken(p)))
        val serialStoreSlotLive = Output(Bool())
        val lsuLive = Output(UInt(memoryEntries.W))
        val physicalResponseFire = Output(Bool())
        val upstreamResponseFire = Output(Bool())
        // Mutually exclusive: 0 no stall/start; 1 context/strong boundary; 2 posted;
        // 3 unknown older store; 4 uncanonical older memory; 5 physical alias;
        // 6 LSU serial/capacity; 7 commit disabled; 8 recovery; 9 other.
        val memoryStall = Output(UInt(4.W))
        val canonicalOrigin = Output(Valid(new CanonicalStoreOrigin(p)))
        val canonicalChecked = Output(Valid(new CanonicalStoreCertificate(p)))
    })
    val decoded = Seq.tabulate(2) { lane =>
        val decoder = Module(new IntegerDecode(enableSystem = p.machineSystem, enableAtomic = p.atomicMemory,
            parallelLegality = p.parallelDecodeLegality, parallelBitLegality = p.parallelBitLegality,
            experimentalFloatingPoint = p.fpEnabled, floatingPointConfig = p.fpConfig))
        decoder.io.instruction := (if (lane == 0) io.instruction0.bits else io.instruction1.bits)
        decoder.io.pc := (if (lane == 0) io.pc0 else io.pc1)
        val request = Wire(Valid(new IntegerRequest))
        request.valid := (if (lane == 0) io.instruction0.valid else io.instruction1.valid)
        request.bits := decoder.io.decoded
        request
    }
    val allocate0 = decoded(0)
    val allocate1 = decoded(1)
    io.decoded0 := allocate0.bits
    io.decoded1 := allocate1.bits
    val backend = Module(ReadyStoreQuery77BackendFactory.create(profile, preselectRedirectTokenMatches, shadowEarlyProofBind,
        proofBankQuiesceIntent, proofBankOwnerCleanup, factorPreparedStorePool, projectedRequestHead, registeredMemoryPreparationDescriptor, earlyLoadPreparationDescriptor, backendNaturalAlignedPmp, virtualStoreOperandLookahead, bankedStoreData))
    io.storeDataWriteMask := backend.storeDataRam.map(r => VecInit(r.io.write.map(w => BoringUtils.bore(w.valid))).asUInt).getOrElse(0.U)
    require(backend.p == p && backend.ledger.p == p)
    require(backend.registerCanonicalStoreEvent == p.registeredCanonicalStoreEvent &&
        backend.retirementSlotIdentity == p.retirementSlotIdentity)
    val adapter = Module(new DataTranslationAdapter(p, entries = 8, registerCheckedRequests = true,
        translationHitFlow = profile.translationHitFlow, usePublishedPmpChanges = p.pmpChangePublicationEnabled,
        queuedHeadSelection = p.queuedHeadSelection, alignedNextLinePmp = p.alignedNextLinePmp))
    val translation = Module(new SvTranslationService(p.virtualMemoryLevels, profile.dataTranslationEntries,
        p.pmpEntries, loadPeek = enabled, writeReadReuse = profile.dataTlbWriteReadReuse))
    backend.io.rawDestinations.foreach { ports =>
        ports(0) := allocate0.bits.rename.rd
        ports(1) := allocate1.bits.rename.rd
    }
    backend.io.rawRequests.foreach { ports =>
        ports(0) := allocate0.bits.rename
        ports(1) := allocate1.bits.rename
    }
    backend.io.fetchFaultMask.foreach(_ := 0.U)
    backend.io.externalPrefetchBusy.foreach(_ := io.control.map(_.prefetchBusy).getOrElse(false.B))
    backend.io.allocate(0) := allocate0
    backend.io.allocate(1) := allocate1
    backend.io.commitEnable := io.commitEnable
    backend.io.recover := io.recover
    backend.io.inspectRegister := io.inspectRegister
    backend.io.imsic.get.request.ready := true.B
    backend.io.imsic.get.response.valid := false.B
    backend.io.imsic.get.response.bits := 0.U.asTypeOf(backend.io.imsic.get.response.bits)
    backend.io.externalInterrupt.get := io.control.map(_.externalInterrupt).getOrElse(false.B)
    backend.io.supervisorExternalInterrupt.get := false.B
    backend.io.timerInterrupt.get := io.control.map(_.timerInterrupt).getOrElse(false.B)
    backend.io.timeValue.get := 0.U
    backend.io.emptyPc.get := 0.U
    backend.io.fetchQuiescent.get := !io.control.map(_.holdFetch).getOrElse(false.B)
    backend.io.fenceIFlushReady.get := true.B
    val flush = backend.io.vmFlush.get && adapter.io.idle && translation.io.idle
    backend.io.vmFlushReady.get := adapter.io.idle && translation.io.idle
    translation.io.flush := flush
    adapter.io.vmState := backend.io.vmState.get
    adapter.io.pmpState := backend.io.pmpState.get
    translation.io.pmpState := backend.io.pmpState.get
    val responses = Module(new DataResponseBuffer(registerPayload = p.registeredTranslatedResponses,
        registerHead = p.registeredTranslationHeads, emptyFlow = p.translatedResponseEmptyFlow,
        returnConfig = p.cpuReturnConfig))
    responses.io.upstream <> backend.io.memory
    adapter.io.virtual <> responses.io.downstream
    adapter.io.pmpRawChanged.get := backend.io.pmpRawChanged.get
    // There is no posted cache in this component. These virtual workloads cannot
    // generate original-physical posted authority; all actual replies are real.
    val posted = backend.io.posted.get
    val transport = adapter.io.posted.get
    transport.upstreamProof := posted.requestProof
    transport.externalBusy := false.B
    posted.externalBusy := false.B
    posted.contextEpoch := transport.contextEpoch
    posted.blockNew := transport.contextChanging || io.control.map(_.blockNew).getOrElse(false.B)
    transport.aggregateDrained := !backend.io.memoryBusy && adapter.io.idle &&
        !posted.busy && !posted.starting && !posted.requestProof.valid
    assert(!transport.requestProof.valid, "virtual-only component must not create posted cache authority")
    translation.io.client <> adapter.io.translation
    io.canonicalOrigin := 0.U.asTypeOf(io.canonicalOrigin)
    io.canonicalChecked := 0.U.asTypeOf(io.canonicalChecked)
    if (overlap) {
        adapter.io.canonicalStoreOrigin.get := backend.io.canonicalStore.get.requestOrigin
        backend.io.canonicalStore.get.checked := adapter.io.canonicalStoreCertificate.get
        io.canonicalOrigin := backend.io.canonicalStore.get.requestOrigin
        io.canonicalChecked := adapter.io.canonicalStoreCertificate.get
    }
    adapter.io.frozenStoreProof.get := backend.io.canonicalStore.get.requestFrozenProof.get
    io.upstreamFrozen := backend.io.canonicalStore.get.requestFrozenProof.get
    io.upstreamRequest.valid := backend.io.memory.request.valid
    io.upstreamRequest.bits := backend.io.memory.request.bits
    io.physical <> adapter.io.physical
    io.pte <> translation.io.memory
    io.queryWrite := false.B
    io.querySize := 0.U
    io.queryPbmt := 0.U
    io.queryValid := false.B
    io.queryHit := false.B
    io.queryAddress := 0.U
    io.queryPhysical := 0.U
    io.epoch := 0.U
    if (enabled) {
        backend.io.loadPrecheck.get <> adapter.io.loadPrecheck.get
        adapter.io.precheckFlush.get := flush
        translation.io.loadPeek.get <> adapter.io.translationPeek.get
        io.queryValid := backend.io.loadPrecheck.get.request.valid
        io.queryHit := backend.io.loadPrecheck.get.response.valid
        io.queryAddress := backend.io.loadPrecheck.get.request.bits.address
        io.queryWrite := backend.io.loadPrecheck.get.request.bits.write
        io.querySize := backend.io.loadPrecheck.get.request.bits.size
        io.queryPbmt := backend.io.loadPrecheck.get.response.bits.pbmt
        io.queryPhysical := backend.io.loadPrecheck.get.response.bits.physicalAddress
        io.epoch := adapter.io.loadPrecheck.get.epoch
    }
    io.proof := 0.U.asTypeOf(io.proof)
    io.proofSecond := 0.U.asTypeOf(io.proofSecond)
    io.proofBoundMask := 0.U
    io.creditActiveMask := 0.U
    io.creditReservedMask := 0.U
    io.creditOwnerSecond := 0.U.asTypeOf(io.creditOwnerSecond)
    io.b2Accepted := backend.lsu.io.boundHeadStoreOverlapAccepted.map(BoringUtils.bore(_)).getOrElse(false.B)
    io.lsuIdleMask := VecInit(backend.lsu.slots.map(slot => !BoringUtils.bore(slot.io.busy))).asUInt
    io.bound := false.B
    io.creditReserved := false.B
    io.creditActive := false.B
    io.creditOwner := 0.U.asTypeOf(io.creditOwner)
    if (enabledProof) {
        io.proof := BoringUtils.bore(backend.pendingStoreProof.get.io.proofs(0))
        io.bound := BoringUtils.bore(backend.pendingStoreProof.get.io.bound).apply(0)
        io.creditReserved := BoringUtils.bore(backend.pendingStoreCredit.get.io.reserved(0))
        io.proofBoundMask := BoringUtils.bore(backend.pendingStoreProof.get.io.bound)
        io.creditReservedMask := BoringUtils.bore(backend.pendingStoreCredit.get.io.reserved).asUInt
        io.creditActiveMask := BoringUtils.bore(backend.pendingStoreCredit.get.io.active).asUInt
        if (proofRows >= 2) io.proofSecond := BoringUtils.bore(backend.pendingStoreProof.get.io.proofs(1))
        if (earlyCredits == 2) io.creditOwnerSecond := BoringUtils.bore(backend.pendingStoreCredit.get.io.owner(1))
        io.creditActive := BoringUtils.bore(backend.pendingStoreCredit.get.io.active(0))
        io.creditOwner := BoringUtils.bore(backend.pendingStoreCredit.get.io.owner(0))
    }
    val bank = backend.pendingStoreProof.get
    io.actualQueryEnabled := p.pendingReadyStoreQuery.B
    io.actualHead := BoringUtils.bore(backend.head)
    io.selectedLoadValid := BoringUtils.bore(bank.io.loadCandidate.valid)
    io.selectedToken := BoringUtils.bore(bank.io.loadCandidate.bits.token)
    io.queryEligibleMask := BoringUtils.bore(bank.io.queryEligible)
    io.queryMask := BoringUtils.bore(bank.queryMask)
    io.presentOwners := BoringUtils.bore(bank.presentOwners)
    io.bankAdmission := BoringUtils.bore(bank.admission)
    io.bankAdmitIndex := BoringUtils.bore(bank.admitIndex)
    io.bankEmpty := BoringUtils.bore(bank.empty)
    io.queryPaused := BoringUtils.bore(bank.io.pause) || BoringUtils.bore(bank.io.flushQueries)
    io.queryStable := BoringUtils.bore(bank.io.precheck.stable)
    io.creditAvailable := BoringUtils.bore(backend.pendingStoreCredit.get.io.available)
    // Passive coverage only. Independent host instruction/byte oracle remains authoritative.
    io.poolBare := !BoringUtils.bore(backend.virtualized)
    io.poolOriginalMask := VecInit(backend.memoryCandidates.map(c => BoringUtils.bore(c.valid))).asUInt
    io.descriptorValid := backend.preparationDescriptorValid.map(BoringUtils.bore(_)).getOrElse(false.B)
    io.descriptorToken := backend.preparationDescriptor.map(d => BoringUtils.bore(d.token))
        .getOrElse(0.U.asTypeOf(new RobToken(p)))
    io.descriptorSaved := backend.preparationDescriptor.map(d => BoringUtils.bore(d.saved)).getOrElse(false.B)
    io.poolStageValid := BoringUtils.bore(backend.stagedMemoryValid.get)
    io.poolStageToken := BoringUtils.bore(backend.stagedMemoryToken.get)
    io.poolStageAddress := BoringUtils.bore(backend.stagedMemoryAddress.get)
    io.poolStageIndex := BoringUtils.bore(backend.stagedMemoryIndex.get)
    io.poolStageData := BoringUtils.bore(backend.stagedMemoryData.get)
    io.poolStageSize := BoringUtils.bore(backend.stagedMemorySize.get)
    io.probeAddressKnown := VecInit(backend.storeAddressKnown.map(BoringUtils.bore(_)))(io.probeIndex)
    io.probeOwnerValid := VecInit(bank.io.owners.map(o => BoringUtils.bore(o.valid)))(io.probeIndex)
    io.probeOlder := VecInit(backend.ages.map(a => BoringUtils.bore(a)))(io.probeIndex) <
        BoringUtils.bore(backend.memoryChoice.age)
    io.shadow.foreach { s =>
        s.mask := BoringUtils.bore(backend.shadowProofBindMask)
        s.offer := BoringUtils.bore(backend.shadowProofBindOffer)
        s.actualMask := BoringUtils.bore(backend.pendingStoreProof.get.io.bind)
        s.systemPending := BoringUtils.bore(backend.proofHeadSystemPending)
        s.reserveSystem := BoringUtils.bore(backend.reserveSystem)
        s.irqDrain := BoringUtils.bore(backend.interruptDrain)
        s.evict := BoringUtils.bore(backend.pendingStoreProof.get.evict)
        s.slot := backend.lsu.io.ordinaryLoadCapacity.map(c => BoringUtils.bore(c.slot)).getOrElse(0.U)
    }
    io.probeAtHead := BoringUtils.bore(backend.memoryPreparationHeadOwner.get).apply(io.probeIndex)
    io.probeDataReady := VecInit(backend.pendingStoreDataReady.map(BoringUtils.bore(_)))(io.probeIndex)
    io.probePending := BoringUtils.bore(backend.pending).apply(io.probeIndex)
    io.probeToken := VecInit((0 until p.robEntries).map(i =>
        BoringUtils.bore(backend.issueEntries(i).renamed.token)))(io.probeIndex)
    io.lsuRequestFire := BoringUtils.bore(backend.lsu.io.memory.request.valid) && BoringUtils.bore(backend.lsu.io.memory.request.ready)
    io.lsuRequestOwner := BoringUtils.bore(backend.lsu.io.requestOwner)
    io.lsuOffer := BoringUtils.bore(backend.lsu.io.start.valid)
    io.lsuReady := BoringUtils.bore(backend.lsu.io.start.ready)
    io.lsuStore := BoringUtils.bore(backend.lsu.io.start.bits.store)
    io.lsuFrozen := BoringUtils.bore(backend.lsu.io.start.bits.frozenStoreProof.get)
    for ((out, i) <- Seq(io.lsuOwner0, io.lsuOwner1, io.lsuOwner2, io.lsuOwner3).zipWithIndex) {
        out.valid := BoringUtils.bore(backend.lsu.io.live(i))
        out.bits := BoringUtils.bore(backend.lsu.io.owner(i))
    }
    io.serialStoreOwner.valid := BoringUtils.bore(backend.memoryProtected)
    io.serialStoreOwner.bits := BoringUtils.bore(backend.memoryOwner)
    io.serialStoreSlotLive := (0 until memoryEntries).map { i =>
        BoringUtils.bore(backend.lsu.io.live(i)) && !BoringUtils.bore(backend.lsu.parallel(i)) &&
            BoringUtils.bore(backend.lsu.io.owner(i)).asUInt === io.serialStoreOwner.bits.asUInt
    }.reduce(_ || _)
    io.lsuLive := VecInit((0 until memoryEntries).map(i => BoringUtils.bore(backend.lsu.io.live(i)))).asUInt
    io.physicalResponseFire := io.physical.response.fire
    io.upstreamResponseFire := backend.io.memory.response.fire
    val candidate = BoringUtils.bore(backend.memoryChoice.valid)
    val contextBlock = BoringUtils.bore(backend.interruptDrain) || BoringUtils.bore(backend.reserveSystem) ||
        BoringUtils.bore(backend.olderSystem) || BoringUtils.bore(backend.fpMemoryEpoch) ||
        BoringUtils.bore(backend.contextMemoryEpoch)
    val postedBlock = !BoringUtils.bore(backend.postedLaunchAllowed)
    val unknownBlock = BoringUtils.bore(backend.unknownOlderStore)
    val canonicalBlock = BoringUtils.bore(backend.precheckedLoad) && BoringUtils.bore(backend.olderUncanonicalMemory)
    val aliasBlock = BoringUtils.bore(backend.physicalStoreConflict)
    val lsuBlock = !BoringUtils.bore(backend.lsu.io.issueAvailable)
    val recoveryBlock = backend.io.recovering || backend.io.recoveryAccepted
    io.memoryStall := Mux(!candidate || io.lsuStart, 0.U,
        Mux(contextBlock, 1.U, Mux(postedBlock, 2.U, Mux(unknownBlock, 3.U,
            Mux(canonicalBlock, 4.U, Mux(aliasBlock, 5.U, Mux(lsuBlock, 6.U,
                Mux(!io.commitEnable, 7.U, Mux(recoveryBlock, 8.U, 9.U)))))))))
    io.lsuStart := BoringUtils.bore(backend.lsu.io.start.valid) && BoringUtils.bore(backend.lsu.io.start.ready)
    io.lsuParallel := BoringUtils.bore(backend.lsu.io.parallel)
    io.lsuPrechecked := BoringUtils.bore(backend.lsu.io.start.bits.precheckedLoad)
    io.lsuVa := BoringUtils.bore(backend.lsu.io.start.bits.address)
    io.lsuPa := BoringUtils.bore(backend.lsu.io.start.bits.physicalAddress)
    io.lsuToken := BoringUtils.bore(backend.lsu.io.start.bits.token)
    io.upstreamFire := backend.io.memory.request.fire
    io.upstreamPrechecked := backend.io.memory.request.bits.precheckedLoad
    io.upstreamAddress := backend.io.memory.request.bits.address
    io.renamed0 := backend.io.renamed(0)
    io.renamed1 := backend.io.renamed(1)
    io.commit0 := backend.io.commit(0)
    io.commit1 := backend.io.commit(1)
    io.issued0 := backend.io.issued(0)
    io.issued1 := backend.io.issued(1)
    io.recoveryAccepted := backend.io.recoveryAccepted
    io.recovering := backend.io.recovering
    io.occupancy := backend.io.occupancy
    io.redirect := backend.io.redirect; io.trap := backend.io.trap.get
    io.headException := backend.io.headException
    io.committedValue := backend.io.committedValue
    io.translationHit := translation.io.tlbHit
    io.translationWalk := translation.io.walkStart
    io.vm := backend.io.vmState.get
    io.idle := adapter.io.idle && translation.io.idle && !backend.io.memoryBusy && backend.io.occupancy === 0.U
}

object ReadyStoreQuery77BackendGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)), "fresh-output enabled0|1")
    val out = Paths.get(args(0)); require(!Files.exists(out), "fresh output required")
    var actual: Option[OooParams] = None
    var actualArguments: Option[Map[String, Boolean]] = None
    ChiselStage.emitCHIRRTLFile({
        val dut = new ReadyStoreQuery77BackendGsim(args(1) == "1")
        actual = Some(dut.backend.p)
        actualArguments = Some(ReadyStoreQuery77BackendFactory.arguments(dut.profile))
        dut
    }, Array("--target-dir", out.toString))
    require(actual.contains(ReadyStoreQuery77Profile.select(args(1) == "1").coreParams))
    require(actualArguments.nonEmpty && actualArguments.get.values.forall(identity))
    Files.writeString(out.resolve("actual-backend-arguments.json"), PostedBoardConfiguration.json(actualArguments.get) + "\n")
    Files.writeString(out.resolve("actual-core.json"), PostedBoardConfiguration.json(actual.get) + "\n")
    Files.writeString(out.resolve("scope.txt"),
        "Exact core params; rows2/credits2/ROB16/PRF48/LSU4/tag64; direct ordered tagged physical/PTE responder; no cache/Home/board.\n")
}
