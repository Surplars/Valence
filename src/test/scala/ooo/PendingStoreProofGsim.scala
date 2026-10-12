package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

/** Independent qualification only: no board preset enables this prototype. */
object PendingStoreProofFixture {
    def params(enabled: Boolean = true, slots: Int = 1): OooParams =
        BoardSocConfig.timingParams("staged-load-issue").copy(
            robEntries = 16, physicalRegs = 48, memoryEntries = 4, tagBits = 64,
            machineSystem = true, atomicMemory = true, pmpEntries = 16, virtualMemoryLevels = 3,
            virtualRamLoadPrecheck = true, canonicalVirtualStoreOverlap = true,
            bufferedRamStores = true, registeredMemoryRequests = true, registeredTranslationHeads = true,
            registeredTranslatedResponses = true, registeredFabricBoundary = true,
            registeredLoadReplay = true, loadOrderOlderRetire = true,
            parallelMemoryPreparation = true, parallelMemoryPayload = true, compactMemoryOperandSelect = true,
            precheckedDataRequestFlow = false, fastBufferedStoreRetire = false, fastHeadLoadRetire = false,
            speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 65536,
            memoryProofFrontier = false, frozenStoreProofTransport = true,
            pendingVirtualStoreProof = enabled, pendingVirtualStoreProofSlots = slots)
    def pmp(cfg: UInt, address: UInt): PmpState = {
        val state = WireDefault(0.U.asTypeOf(new PmpState))
        state.cfg(0) := cfg
        state.addr(0) := address
        PmpState.decodeRegions(state)
        state
    }
}

/** Component contracts. Synthetic hit replies test the production shared registered
  * PMP/certificate logic; actual translation is covered by the separate real backend.
  */
class PendingStoreProofBankGsim(slots: Int = 1, credits: Int = 1) extends Module {
    val p = PendingStoreProofFixture.params(slots = slots).copy(pendingStoreEarlyLoadCredits = credits)
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
        val load = Input(Valid(new VirtualRamLoadCandidate(p)))
        val reply = Input(Valid(new VirtualLoadPrecheckResponse))
        val query = Output(Valid(new VirtualLoadPrecheckRequest))
        val loadPrepared = Output(Valid(new VirtualRamLoadCertificate(p)))
        val pmpCfg = Input(UInt(8.W))
        val pmpAddress = Input(UInt(54.W))
        val bind = Input(UInt(2.W))
        val consume = Input(Valid(new RobToken(p)))
        val proof0 = Output(Valid(new MemoryAddressProof(p)))
        val proof1 = Output(Valid(new MemoryAddressProof(p)))
        val bound = Output(UInt(2.W))
        val reservedCount = Output(UInt(2.W))
        val provedCount = Output(UInt(2.W))
        val creditReserve = Input(Valid(new RobToken(p)))
        val creditConsume = Input(Valid(new RobToken(p)))
        val creditCancel = Input(Valid(new RobToken(p)))
        val live0 = Input(Valid(new RobToken(p)))
        val live1 = Input(Valid(new RobToken(p)))
        val creditAvailable = Output(Bool())
        val creditReserved = Output(Bool())
        val creditActive = Output(Bool())
        val creditOwner = Output(new RobToken(p))
        val creditActiveMask = Output(UInt(2.W))
        val creditReservedMask = Output(UInt(2.W))
        val creditOwnerSecond = Output(new RobToken(p))
    })
    val bank = Module(new PendingVirtualStoreProof(p))
    bank.io.head := io.head
    bank.io.owners := 0.U.asTypeOf(bank.io.owners)
    for (owner <- Seq(io.owner0, io.owner1, io.owner2)) {
        when(owner.valid) { bank.io.owners(owner.bits.token.index) := owner }
    }
    bank.io.clearOwners := io.clearOwners
    bank.io.queryEligible := io.queryEligible
    bank.io.pause := io.pause
    bank.io.flushQueries := io.flush
    bank.io.loadCandidate := io.load
    bank.io.precheck.epoch := io.epoch
    bank.io.precheck.stable := io.stable
    bank.io.precheck.response := io.reply
    bank.io.pmpState := PendingStoreProofFixture.pmp(io.pmpCfg, io.pmpAddress)
    bank.io.privilege := 1.U
    bank.io.bind := io.bind(slots - 1, 0)
    bank.io.consume := io.consume
    io.query := bank.io.precheck.request
    io.loadPrepared := bank.io.loadPrepared
    io.proof0 := bank.io.proofs(0)
    io.proof1 := (if (slots == 2) bank.io.proofs(1) else 0.U.asTypeOf(io.proof1))
    io.bound := bank.io.bound
    io.reservedCount := bank.io.reservedCount
    io.provedCount := bank.io.provedCount
    val credit = Module(new PendingStoreEarlyLoadCredit(p))
    credit.io.reserve := io.creditReserve
    credit.io.consume := io.creditConsume
    credit.io.cancelReservation := io.creditCancel
    credit.io.liveOwners := 0.U.asTypeOf(credit.io.liveOwners)
    credit.io.liveOwners(0) := io.live0
    credit.io.liveOwners(1) := io.live1
    io.creditAvailable := credit.io.available
    io.creditReserved := credit.io.reserved(0)
    io.creditActive := credit.io.active(0)
    io.creditOwner := credit.io.owner(0)
    io.creditActiveMask := credit.io.active.asUInt
    io.creditReservedMask := credit.io.reserved.asUInt
    io.creditOwnerSecond := (if (credits == 2) credit.io.owner(1) else 0.U.asTypeOf(io.creditOwnerSecond))
}

object PendingStoreProofBankGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new PendingStoreProofBankGsim(args.lift(1).map(_.toInt).getOrElse(1),
        args.lift(2).map(_.toInt).getOrElse(1)),
        Array("--target-dir", args.head))
}

class PendingStoreProofTransportGsim(enabled: Boolean) extends Module {
    val p = PendingStoreProofFixture.params(enabled = false)
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val origin = Input(Valid(new CanonicalStoreOrigin(p)))
        val frozen = Input(Valid(new FrozenStoreProof))
        val physical = new DataPort
        val pte = new SvPteReadPort
        val context = Input(new VmCsrState)
        val pmpCfg = Input(UInt(8.W))
        val pmpAddress = Input(UInt(54.W))
        val flush = Input(Bool())
        val query = Input(Valid(new VirtualLoadPrecheckRequest))
        val queryHit = Output(Valid(new VirtualLoadPrecheckResponse))
        val epoch = Output(UInt(32.W))
        val stable = Output(Bool())
        val bufferRequest = Output(Valid(new DataRequest))
        val bufferOrigin = Output(Valid(new CanonicalStoreOrigin(p)))
        val bufferFrozen = Output(Valid(new FrozenStoreProof))
        val bufferFire = Output(Bool())
        val checked = Output(Valid(new CanonicalStoreCertificate(p)))
        val translationWalk = Output(Bool())
        val idle = Output(Bool())
    })
    val buffer = Module(new StoreBuffer(p))
    val adapter = Module(new DataTranslationAdapter(p, registerCheckedRequests = true,
        registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent))
    val translation = Module(new SvTranslationService(3, 16, 16, loadPeek = true, writeReadReuse = true))
    val pmp = PendingStoreProofFixture.pmp(io.pmpCfg, io.pmpAddress)
    buffer.io.upstream <> io.upstream
    buffer.io.upstreamCanonicalStoreOrigin.get := io.origin
    buffer.io.upstreamFrozenStoreProof.foreach(_ := io.frozen)
    buffer.io.fastStore.valid := false.B
    buffer.io.fastStore.bits := 0.U.asTypeOf(buffer.io.fastStore.bits)
    buffer.io.upstreamProof.foreach(_ := 0.U.asTypeOf(buffer.io.upstreamProof.get))
    buffer.io.fastProof.foreach(_ := 0.U.asTypeOf(buffer.io.fastProof.get))
    buffer.io.externalPostedBusy.foreach(_ := false.B)
    adapter.io.virtual <> buffer.io.memory
    adapter.io.canonicalStoreOrigin.get := buffer.io.memoryCanonicalStoreOrigin.get
    adapter.io.frozenStoreProof.foreach(_ := buffer.io.memoryFrozenStoreProof.get)
    adapter.io.vmState := io.context
    adapter.io.pmpState := pmp
    adapter.io.loadPrecheck.get.request := io.query
    adapter.io.precheckFlush.get := io.flush
    translation.io.client <> adapter.io.translation
    translation.io.loadPeek.get <> adapter.io.translationPeek.get
    translation.io.pmpState := pmp
    translation.io.flush := io.flush
    io.physical <> adapter.io.physical
    io.pte <> translation.io.memory
    io.queryHit := adapter.io.loadPrecheck.get.response
    io.epoch := adapter.io.loadPrecheck.get.epoch
    io.stable := adapter.io.loadPrecheck.get.stable
    io.bufferRequest.valid := buffer.io.memory.request.valid
    io.bufferRequest.bits := buffer.io.memory.request.bits
    io.bufferOrigin := buffer.io.memoryCanonicalStoreOrigin.get
    io.bufferFrozen := buffer.io.memoryFrozenStoreProof.getOrElse(0.U.asTypeOf(io.bufferFrozen))
    io.bufferFire := buffer.io.memory.request.fire
    io.checked := adapter.io.canonicalStoreCertificate.get
    io.translationWalk := translation.io.walkStart
    io.idle := adapter.io.idle && translation.io.idle && !buffer.io.busy
}

object PendingStoreProofTransportGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new PendingStoreProofTransportGsim(true), Array("--target-dir", args.head))
}

class PendingStoreProofBackendGsim(enabledProof: Boolean, enabledBoundOverlap: Boolean = false,
    enabledReadyStoreBypass: Boolean = false, proofRows: Int = 1, earlyCredits: Int = 1,
    registeredQuery: Boolean = false, registeredCanonicalEvent: Boolean = false,
    sharedLane1OwnerMatch: Boolean = false, matchedOwnerProfile: Boolean = false,
    directRank1MemorySourceIds: Boolean = false) extends Module {
    private val enabled = true
    private val overlap = true
    private val memoryEntries = 4
    private val historicalParams = PendingStoreProofFixture.params(enabled = enabledProof, slots = proofRows).copy(
        boundHeadStoreOverlap = enabledBoundOverlap, pendingReadyStoreBypass = enabledReadyStoreBypass,
        pendingStoreEarlyLoadCredits = earlyCredits, registeredPendingStoreQuery = registeredQuery,
        registeredCanonicalStoreEvent = registeredCanonicalEvent, sharedLane1OwnerMatch = sharedLane1OwnerMatch)
    val p = (if (matchedOwnerProfile) Lane1OwnerBackendProfile.params(sharedLane1OwnerMatch) else historicalParams)
        .copy(directRank1MemorySourceIds = directRank1MemorySourceIds)
    val io = IO(new Bundle {
        val instruction0 = Input(Valid(UInt(32.W)))
        val instruction1 = Input(Valid(UInt(32.W)))
        val pc0 = Input(UInt(64.W))
        val pc1 = Input(UInt(64.W))
        val decoded0 = Output(new IntegerRequest)
        val decoded1 = Output(new IntegerRequest)
        val probeIndex = Input(UInt(4.W))
        val probeDataReady = Output(Bool())
        val probePending = Output(Bool())
        val probeToken = Output(new RobToken(p))
        val proof = Output(Valid(new MemoryAddressProof(p)))
        val proofSecond = Output(Valid(new MemoryAddressProof(p)))
        val proofBoundMask = Output(UInt(2.W))
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
        val upstreamRequest = Output(Valid(new DataRequest))
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
        val physical = new DataPort
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
        val decoder = Module(new IntegerDecode(enableSystem = true, enableAtomic = true,
            parallelLegality = p.parallelDecodeLegality, parallelBitLegality = p.parallelBitLegality))
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
    val backend = Module(new IntegerBackend(p,
        registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent))
    val adapter = Module(new DataTranslationAdapter(p, registerCheckedRequests = true,
        registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent))
    val translation = Module(new SvTranslationService(3, 16, 16, loadPeek = enabled, writeReadReuse = true))
    backend.io.rawDestinations.foreach { ports =>
        ports(0) := allocate0.bits.rename.rd
        ports(1) := allocate1.bits.rename.rd
    }
    backend.io.rawRequests.foreach { ports =>
        ports(0) := allocate0.bits.rename
        ports(1) := allocate1.bits.rename
    }
    backend.io.fetchFaultMask.foreach(_ := 0.U)
    backend.io.externalPrefetchBusy.foreach(_ := false.B)
    backend.io.allocate(0) := allocate0
    backend.io.allocate(1) := allocate1
    backend.io.commitEnable := io.commitEnable
    backend.io.recover := io.recover
    backend.io.inspectRegister := io.inspectRegister
    backend.io.imsic.get.request.ready := true.B
    backend.io.imsic.get.response.valid := false.B
    backend.io.imsic.get.response.bits := 0.U.asTypeOf(backend.io.imsic.get.response.bits)
    backend.io.externalInterrupt.get := false.B
    backend.io.supervisorExternalInterrupt.get := false.B
    backend.io.timerInterrupt.get := false.B
    backend.io.timeValue.get := 0.U
    backend.io.emptyPc.get := 0.U
    backend.io.fetchQuiescent.get := true.B
    backend.io.fenceIFlushReady.get := true.B
    val flush = backend.io.vmFlush.get && adapter.io.idle && translation.io.idle
    backend.io.vmFlushReady.get := adapter.io.idle && translation.io.idle
    translation.io.flush := flush
    adapter.io.vmState := backend.io.vmState.get
    adapter.io.pmpState := backend.io.pmpState.get
    translation.io.pmpState := backend.io.pmpState.get
    adapter.io.virtual <> backend.io.memory
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
        if (proofRows == 2) io.proofSecond := BoringUtils.bore(backend.pendingStoreProof.get.io.proofs(1))
        if (earlyCredits == 2) io.creditOwnerSecond := BoringUtils.bore(backend.pendingStoreCredit.get.io.owner(1))
        io.creditActive := BoringUtils.bore(backend.pendingStoreCredit.get.io.active(0))
        io.creditOwner := BoringUtils.bore(backend.pendingStoreCredit.get.io.owner(0))
    }
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

object PendingStoreProofBackendGsimMain extends App {
    require(args.length >= 2 && args.length <= 11 && args.slice(1, 4).forall(Set("0", "1").contains))
    require(args.slice(4, 6).forall(Set("1", "2").contains))
    require(args.slice(6, 11).forall(Set("0", "1").contains))
    ChiselStage.emitCHIRRTLFile({
        val dut = new PendingStoreProofBackendGsim(args(1) == "1", args.lift(2).contains("1"),
            args.lift(3).contains("1"), args.lift(4).map(_.toInt).getOrElse(1),
            args.lift(5).map(_.toInt).getOrElse(1), args.lift(6).contains("1"), args.lift(7).contains("1"),
            args.lift(8).contains("1"), args.lift(9).contains("1"), args.lift(10).contains("1"))
        require(dut.backend.p == dut.p && dut.backend.ledger.p == dut.p,
            "actual backend and ledger constructor products must match the requested complete profile")
        require(dut.backend.executionStages.size == 2 && dut.p.registeredIssueExecute && dut.p.parallelIssuePayload)
        require(dut.backend.ledger.p.sharedLane1OwnerMatch == dut.p.sharedLane1OwnerMatch)
        require(dut.backend.ledger.io.lane1OwnerMatch.nonEmpty == dut.p.sharedLane1OwnerMatch)
        println(s"LANE1_OWNER_MATCH shared=${dut.p.sharedLane1OwnerMatch} " +
            s"registered=${dut.p.registeredIssueExecute} rawPayload=${dut.p.parallelIssuePayload} tagBits=${dut.p.tagBits}")
        if (args.lift(9).contains("1")) {
            require(dut.p == Lane1OwnerBackendProfile.params(args.lift(8).contains("1"))
                .copy(directRank1MemorySourceIds = args.lift(10).contains("1")))
            PostedBoardConfiguration.writeCore(Lane1OwnerBackendProfile.abc, args.head + "/published-abc")
            PostedBoardConfiguration.writeCore(dut.backend.p, args.head)
        }
        val actualQuery = TimingBatchActualAudit.requireQueryStage(
            dut.p.registeredPendingStoreQuery, dut.backend.pendingStoreProof)
        println(s"PENDING_BACKEND_QUERY_STAGE registered=$actualQuery " +
            s"proofRows=${dut.p.pendingVirtualStoreProofSlots} credits=${dut.p.pendingStoreEarlyLoadCredits}")
        require(dut.backend.registerCanonicalStoreEvent == dut.p.registeredCanonicalStoreEvent &&
            dut.adapter.registerCanonicalStoreEvent == dut.p.registeredCanonicalStoreEvent)
        println(s"PENDING_BACKEND_CANONICAL_STAGE backend=${dut.backend.registerCanonicalStoreEvent} " +
            s"adapter=${dut.adapter.registerCanonicalStoreEvent}")
        dut
    }, Array("--target-dir", args.head))
}
