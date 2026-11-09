package soc.core.inorder

import chisel3._
import chisel3.util._

/** Optional caches wrap IF/MEM handshakes; named CPU pipeline profiles remain independently selectable. */
class FiveStageCachedCore(val p: FiveStageConfig, externalDataInvalidate: Boolean = false,
    acknowledgedDataInvalidate: Boolean = false, externalQuiesce: Boolean = false,
    runtimeMaintenance: Boolean = false, reportQuiescence: Boolean = false) extends Module {
    require(!runtimeMaintenance || (externalQuiesce && p.coherentCaches))
    require(!acknowledgedDataInvalidate || (externalDataInvalidate && p.coherentCaches))
    private val observeQuiescence = runtimeMaintenance || reportQuiescence
    val io = IO(new Bundle {
        val quiesceRequest = if (externalQuiesce) Some(Input(Bool())) else None
        val architecturalStopped = if (externalQuiesce) Some(Output(Bool())) else None
        val runtimeFlush = if (runtimeMaintenance) Some(Input(Bool())) else None
        val runtimeFlushDone = if (runtimeMaintenance) Some(Output(UInt(2.W))) else None
        val privateCachesQuiescent = if (observeQuiescence) Some(Output(Bool())) else None
        val instructionMemory = new FiveStageBurstPort(p)
        val dataMemory = new FiveStageBurstPort(p)
        val coherent = if (p.coherentCaches) Some(Vec(2, new soc.bus.tilelink.TLBundle(
            soc.bus.tilelink.TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)))) else None
        val uncached = if (p.coherentCaches) Some(Vec(2, new I1DataPort)) else None
        val lineGrants = if (p.coherentLineGrants) Some(Vec(2,
            Flipped(Decoupled(new soc.ip.tilelink.LineGrant(
                soc.bus.tilelink.TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)))))) else None
        val clearCoherentReservation = if (p.coherentCaches) Some(Output(Bool())) else None
        // CPU-clock register transactions; platform crossings require the shared CDC adapter.
        val msi = if (p.withAia) Some(Flipped(new soc.ip.bus.RegisterPort)) else None
        val fenceIFlush = if (p.externalFenceICompletion) Some(Output(Bool())) else None
        val fenceIFlushReady = if (p.externalFenceICompletion) Some(Input(Bool())) else None
        val fenceIFetchDrained = if (p.externalFenceICompletion) Some(Output(Bool())) else None
        val spinor = if (p.spinor) Some(new I1SpinorPort) else None
        val spinorMemoryFault = if (p.spinor && p.withH) Some(Flipped(Valid(new I1SpinorMemoryFault))) else None
        val spinorMemory = if (p.spinor) Some(Flipped(new I1SpinorMemoryPort(p))) else None
        val retire = Valid(new FiveStageRetire(p))
        val trapTaken = Output(Bool())
        val trapPc = Output(UInt(p.xlen.W))
        val trapCause = Output(UInt(p.xlen.W))
        val time = Input(UInt(64.W))
        val externalIrq = Input(Bool())
        val timerIrq = Input(Bool())
        val softwareIrq = Input(Bool())
        val supervisorExternalIrq = if (p.withSupervisor) Some(Input(Bool())) else None
        val invalidateData = if (externalDataInvalidate) Some(Input(Bool())) else None
        val invalidateDataDone = if (acknowledgedDataInvalidate) Some(Output(Bool())) else None
        val invalidateReservation = if (p.withA) Some(Input(Bool())) else None
        val cycles = Output(UInt(64.W))
        val instructions = Output(UInt(64.W))
        val stageValid = Output(UInt(p.pipeline.size.W))
        val branchMispredict = Output(Bool())
        val instructionHit = Output(Bool())
        val instructionMiss = Output(Bool())
        val dataHit = Output(Bool())
        val dataMiss = Output(Bool())
        val stallLoadUse = Output(Bool())
        val stallMemory = Output(Bool())
        val stallMulDiv = Output(Bool())
        val stallFetch = Output(Bool())
        val stallStoreAck = Output(Bool())
        val dataRequestAccepted = Output(Bool())
        val dataRequestOffered = Output(Bool())
    })
    // An overridable construction boundary lets test tops observe the same
    // CPU through its real caches; the production generator and I/O stay unchanged.
    protected def instantiateCore(config: FiveStageConfig, quiesce: Boolean): FiveStageCore =
        new FiveStageCore(config, externalQuiesce = quiesce)
    val core = Module(instantiateCore(p, externalQuiesce))
    // One scalar or vector owner traverses the existing atomic/cache path.
    // Serial vector WB guarantees no competing scalar memory instruction.
    val sharedDataRequest = if (p.spinor) Wire(Decoupled(new FiveStageDataRequest(p)))
        else core.io.dataRequest
    val sharedDataResponse = if (p.spinor) Wire(Decoupled(new FiveStageDataResponse(p)))
        else core.io.dataResponse
    private val sharedDataIdle = if (observeQuiescence && p.spinor) Some(Wire(Bool())) else None
    if (p.spinor) {
        io.spinor.get <> core.io.spinor.get
        val vector = io.spinorMemory.get
        val active = RegInit(false.B)
        val vectorOwner = Reg(Bool())
        val chooseVector = vector.request.valid
        sharedDataRequest.valid := !active && (core.io.dataRequest.valid || vector.request.valid)
        sharedDataRequest.bits := Mux(chooseVector, vector.request.bits, core.io.dataRequest.bits)
        core.io.dataRequest.ready := !active && !chooseVector && sharedDataRequest.ready
        vector.request.ready := !active && chooseVector && sharedDataRequest.ready
        sharedDataResponse.ready := active && Mux(vectorOwner, vector.response.ready, core.io.dataResponse.ready)
        vector.response.valid := active && vectorOwner && sharedDataResponse.valid
        core.io.dataResponse.valid := active && !vectorOwner && sharedDataResponse.valid
        vector.response.bits := sharedDataResponse.bits
        core.io.dataResponse.bits := sharedDataResponse.bits
        when(sharedDataRequest.fire) { active := true.B; vectorOwner := chooseVector }
        when(sharedDataResponse.fire) { active := false.B }
        sharedDataIdle.foreach(_ := !active && !vector.request.valid &&
            !core.io.dataRequest.valid && !sharedDataResponse.valid)
        when(!reset.asBool) {
            assert(!(vector.request.valid && core.io.dataRequest.valid), "scalar/vector memory owners overlap")
            assert(!sharedDataResponse.valid || active, "shared data response has no owner")
        }
    }
    core.io.spinorMemoryFault.foreach(_ := io.spinorMemoryFault.get)
    core.io.quiesceRequest.foreach(_ := io.quiesceRequest.get)
    io.architecturalStopped.foreach(_ := core.io.architecturalStopped.get)
    io.fenceIFlush.foreach(_ := core.io.fenceIFlush.get)
    io.fenceIFetchDrained.foreach(_ := core.io.fenceIFetchDrained.get)
    core.io.fenceIFlushReady.foreach(_ := io.fenceIFlushReady.get)
    val imsic = if (p.withAia) Some(Module(new soc.ip.interrupt.Imsic(
        soc.ip.interrupt.ImsicParams(identities = 127, guestFiles = 0)))) else None
    imsic.foreach { unit =>
        unit.io.mmio <> io.msi.get
        unit.io.csrRequest <> core.io.aia.get.request
        core.io.aia.get.response <> unit.io.csrResponse
    }
    val useInstructionPma = p.fpgaTimingCuts && (p.withSv39 || p.pmpEntries > 0)
    val icache = Module(new FiveStageWordCache(p, p.instructionCacheBytes, allowHitReplacement = true,
        trustedReadOnlyCacheability = useInstructionPma,
        reportMaintenance = runtimeMaintenance, reportQuiescence = observeQuiescence))
    val dcache = Module(new FiveStageWordCache(p, p.dataCacheBytes,
        reportMaintenance = acknowledgedDataInvalidate || runtimeMaintenance,
        reportQuiescence = observeQuiescence))
    io.invalidateDataDone.foreach(_ := dcache.io.invalidateDone.get)
    private val privateArbitrationIdle = if (observeQuiescence) Some(WireDefault(true.B)) else None
    io.runtimeFlushDone.foreach(_ := Cat(dcache.io.invalidateDone.get, icache.io.invalidateDone.get))
    io.privateCachesQuiescent.foreach(_ := icache.io.quiescent.get && dcache.io.quiescent.get &&
        privateArbitrationIdle.get && sharedDataIdle.getOrElse(true.B))
    if (runtimeMaintenance) when(io.runtimeFlush.get) {
        assert(core.io.architecturalStopped.get, "runtime cache flush began before precise core stop")
    }
    val acceptedOrdinaryStore = WireDefault(sharedDataRequest.fire &&
        sharedDataRequest.bits.write && !sharedDataRequest.bits.atomic)
    if (p.coherentCaches) {
        for ((cache, i) <- Seq(icache, dcache).zipWithIndex) {
            io.coherent.get(i) <> cache.io.coherence.get
            io.uncached.get(i) <> cache.io.uncached.get
            cache.io.lineGrant.foreach(_ <> io.lineGrants.get(i))
        }
        io.clearCoherentReservation.get := core.io.clearReservation || io.invalidateData.getOrElse(false.B) ||
            io.invalidateReservation.getOrElse(false.B) ||
            io.runtimeFlush.getOrElse(false.B) || acceptedOrdinaryStore ||
            icache.io.coherence.get.b.fire || dcache.io.coherence.get.b.fire
    }
    private val fetchUpper = RegEnable(core.io.instructionRequest.bits(2), core.io.instructionRequest.fire)
    io.instructionMemory <> icache.io.memory; io.dataMemory <> dcache.io.memory
    icache.io.invalidate := (if (runtimeMaintenance) core.io.invalidateInstructionCache || io.runtimeFlush.get
        else core.io.invalidateInstructionCache)
    dcache.io.invalidate := (if (runtimeMaintenance) io.invalidateData.getOrElse(false.B) || io.runtimeFlush.get
        else io.invalidateData.getOrElse(false.B))
    val fetchRequest = Wire(Decoupled(new FiveStageDataRequest(p)))
    val fetchResponse = Wire(Decoupled(new FiveStageDataResponse(p)))
    val bareInstructionTurnover = if (p.withH) Some(WireDefault(false.B)) else None
    val fetchCandidates = Wire(Vec(2, UInt(p.xlen.W)))
    fetchCandidates.foreach(_ := fetchRequest.bits.address)
    val fetchCandidateSecond = WireDefault(false.B)
    if (p.withC) {
        val aligner = Module(new FiveStageFetchAligner(p))
        aligner.io.request <> core.io.instructionRequest; core.io.instructionResponse <> aligner.io.response
        fetchRequest <> aligner.io.memoryRequest; aligner.io.memoryResponse <> fetchResponse
        aligner.io.bareTurnover.foreach(_ := bareInstructionTurnover.get)
        aligner.io.addressCandidates.foreach(fetchCandidates := _)
        aligner.io.candidateSecond.foreach(fetchCandidateSecond := _)
        // Clear on every privilege/context transition, including traps/xRET,
        // not just SATP/SFENCE. Branch redirects retain the SAME context.
        aligner.io.invalidate.foreach(_ := core.io.invalidateTranslation ||
            core.io.invalidateInstructionCache || core.io.clearReservation)
    } else {
        fetchRequest.valid := core.io.instructionRequest.valid
        fetchRequest.bits := 0.U.asTypeOf(new FiveStageDataRequest(p))
        fetchRequest.bits.address := core.io.instructionRequest.bits
        fetchRequest.bits.size := 2.U
        core.io.instructionRequest.ready := fetchRequest.ready
        core.io.instructionResponse.valid := fetchResponse.valid
        core.io.instructionResponse.bits.instruction := (if (p.xlen == 64)
            Mux(fetchUpper, fetchResponse.bits.data(63, 32), fetchResponse.bits.data(31, 0))
            else fetchResponse.bits.data)
        core.io.instructionResponse.bits.error := fetchResponse.bits.error
        core.io.instructionResponse.bits.pageFault := fetchResponse.bits.pageFault
        core.io.instructionResponse.bits.guest.foreach(_ := fetchResponse.bits.guest.get)
        core.io.instructionResponse.bits.compressed := false.B
        core.io.instructionResponse.bits.secondHalfFault := false.B
        fetchResponse.ready := core.io.instructionResponse.ready
    }
    val physicalAtomicOwner = WireDefault(false.B)
    val physicalDataRequest = Wire(Decoupled(new FiveStageDataRequest(p)))
    val physicalDataResponse = Wire(Decoupled(new FiveStageDataResponse(p)))
    val instructionPhysicalRequest = Wire(Decoupled(new FiveStageDataRequest(p)))
    val instructionPhysicalResponse = Wire(Decoupled(new FiveStageDataResponse(p)))
    // The read-only coherent cache uses occupancy-only admission when control
    // cuts are selected. No extra fetch stage: READY never depends on the new
    // physical address/tag, and the final old response can turn over in-place.
    // Quiescence sees a conservative pre-authorization request bound. No
    // ordinary cache admission, response, probe or owner handshake is altered.
    // The core's registered fetch owner also covers aligner second parcels and
    // same-word reuse. Quiescence never waits on BRAM length -> live fetch VALID.
    icache.io.quiescenceRequestPending.foreach(_ := core.io.fetchOwner)
    dcache.io.quiescenceRequestPending.foreach(_ := sharedDataRequest.valid || physicalAtomicOwner)
    if (observeQuiescence) when(!reset.asBool) {
        assert(!fetchRequest.valid || core.io.fetchOwner,
            "fetch quiescence bound omitted an aligner offer")
    }
    icache.io.request <> instructionPhysicalRequest
    instructionPhysicalResponse <> icache.io.response
    if (p.coherentCaches) {
        dcache.io.request <> physicalDataRequest; physicalDataResponse <> dcache.io.response
    } else if (p.withA) {
        val atomic = Module(new FiveStageAtomicMemory(p))
        physicalAtomicOwner := atomic.io.registeredOwner
        atomic.io.request <> physicalDataRequest; physicalDataResponse <> atomic.io.response
        dcache.io.request <> atomic.io.memoryRequest; atomic.io.memoryResponse <> dcache.io.response
        atomic.io.invalidateReservation := core.io.clearReservation || io.invalidateData.getOrElse(false.B) ||
            io.invalidateReservation.get
    } else {
        dcache.io.request <> physicalDataRequest; physicalDataResponse <> dcache.io.response
    }
    if (p.withSv39 || p.pmpEntries > 0) {
        val splitInstruction = p.fpgaTimingCuts && p.withC && p.fastInstructionTranslation && p.preparedTranslationProofs
        def translation(instruction: Boolean, splitInstruction: Boolean = false,
            splitData: Boolean = false): FiveStageTranslationIO = {
            val registered = instruction && p.fpgaTimingCuts && p.withC && p.fastInstructionTranslation
            if (p.withH) Module(new I1HypervisorTranslation(p, instruction,
                splitInstruction, splitData, registered)).io
            else Module(new FiveStageAddressTranslation(p, instruction,
                splitInstruction, splitData, registered)).io
        }
        val it = translation(instruction = true, splitInstruction = splitInstruction)
        val dt = translation(instruction = false, splitData = core.io.dataCandidates.isDefined)
        for (translator <- Seq(it, dt)) {
            translator.context := core.io.translation; translator.entries := core.io.pmp
            translator.invalidate := core.io.invalidateTranslation
        }
        it.request <> fetchRequest; fetchResponse <> it.response
        bareInstructionTurnover.foreach(_ := it.bareTurnover.get)
        dt.request <> sharedDataRequest; sharedDataResponse <> dt.response
        acceptedOrdinaryStore := dt.ordinaryStoreAccepted.get
        dt.dataCandidates.foreach(_ := core.io.dataCandidates.get)
        dt.dataCandidateEarly.foreach(_ := core.io.dataCandidateEarly.get)
        dt.readAhead.foreach(_ := core.io.dataReadAhead.get)
        instructionPhysicalRequest <> it.physical.request
        it.physical.response <> instructionPhysicalResponse
        icache.io.readCacheable.foreach(_ := it.physicalCacheable.get)
        it.addressCandidates.foreach(_ := fetchCandidates)
        it.candidateSecond.foreach(_ := fetchCandidateSecond)
        // Three logical users, ONE physical D-cache owner. The offer is sticky under READY stalls.
        // PTW does not instantiate a new cache, AXI master, MSHR or unbounded request queue.
        val instructionPending = core.io.fetchOwner || it.registeredOwner
        val dataPending = sharedDataRequest.valid || physicalAtomicOwner || dt.registeredOwner || instructionPending
        icache.io.quiescenceRequestPending.foreach(_ := instructionPending)
        dcache.io.quiescenceRequestPending.foreach(_ := dataPending)
        val ports = Seq(dt.physical, dt.walk, it.walk)
        val active = RegInit(false.B); val owner = Reg(UInt(2.W))
        val offered = RegInit(false.B); val heldGrant = Reg(UInt(2.W))
        dcache.io.quiescenceRequestPending.foreach(_ := dataPending || active || offered)
        // Every routed response below is qualified by active; checking VALID
        // again only duplicates the registered physical-owner proof.
        privateArbitrationIdle.foreach(_ := !active && !offered && !dataPending)
        val roundRobin = RegInit(0.U(2.W))
        val available = ports.map(_.request.valid)
        val choice = if (p.fpgaTimingCuts && (p.coherentBandwidth || p.withH)) {
            // PRIVATE CPU arbiter: finite, read-only Svade walkers take
            // priority, rotating between them. H may translate each VS PTE
            // through G; neither walker retries A/D writes. In-order demand
            // and frontend capacity bound younger work, so both sides drain.
            // Late demand VALID qualifies transfer, never the RAM address.
            // This is not a general unbounded-master fairness policy.
            Mux(roundRobin === 2.U,
                Mux(available(2), 2.U, Mux(available(1), 1.U, 0.U)),
                Mux(available(1), 1.U, Mux(available(2), 2.U, 0.U)))
        } else MuxLookup(roundRobin, Mux(available(0), 0.U, Mux(available(1), 1.U, 2.U)))(Seq(
            1.U -> Mux(available(1), 1.U, Mux(available(2), 2.U, 0.U)),
            2.U -> Mux(available(2), 2.U, Mux(available(0), 0.U, 1.U))))
        val grant = Mux(offered, heldGrant, choice)
        // Replace only the consumed physical owner. READY is now independent
        // of the next D-cache tag when coherentBandwidth selects ordered
        // admission; no queue, MSHR or speculative success is added.
        val physicalSlot = !active || (p.coherentBandwidth.B && physicalDataResponse.fire)
        physicalDataRequest.valid := physicalSlot && VecInit(available)(grant)
        physicalDataRequest.bits := Mux1H((0 until 3).map(i => (grant === i.U) -> ports(i).request.bits))
        physicalDataResponse.ready := active && Mux1H((0 until 3).map(i =>
            (owner === i.U) -> ports(i).response.ready))
        for (i <- 0 until 3) {
            ports(i).request.ready := physicalSlot && grant === i.U && physicalDataRequest.ready
            ports(i).response.valid := active && owner === i.U && physicalDataResponse.valid
            ports(i).response.bits := physicalDataResponse.bits
        }
        when(physicalDataRequest.valid && !physicalDataRequest.ready) { offered := true.B; heldGrant := grant }
        when(physicalDataRequest.fire) {
            active := true.B; owner := grant; offered := false.B
            roundRobin := Mux(grant === 2.U, 0.U, grant + 1.U)
        }
        when(physicalDataResponse.fire && !physicalDataRequest.fire) { active := false.B }
        assert(!physicalDataResponse.valid || active, "physical D-cache reply has no demand/PTW owner")
    } else {
        // Preserve the measured M-only fast path when translation/protection are disabled.
        instructionPhysicalRequest <> fetchRequest; fetchResponse <> instructionPhysicalResponse
        fetchResponse.bits.fetchSpan := true.B
        physicalDataRequest <> sharedDataRequest; sharedDataResponse <> physicalDataResponse
    }
    core.io.time := io.time; core.io.externalIrq := io.externalIrq || imsic.map(_.io.interrupts(0)).getOrElse(false.B)
    core.io.timerIrq := io.timerIrq; core.io.softwareIrq := io.softwareIrq
    core.io.supervisorExternalIrq.foreach(_ := io.supervisorExternalIrq.get ||
        imsic.map(_.io.interrupts(1)).getOrElse(false.B))
    io.retire := core.io.retire; io.cycles := core.io.cycles; io.instructions := core.io.instructions
    io.trapTaken := core.io.trapTaken; io.trapPc := core.io.trapPc; io.trapCause := core.io.trapCause
    io.stageValid := core.io.stageValid; io.branchMispredict := core.io.branchMispredict
    io.instructionHit := icache.io.hit; io.instructionMiss := icache.io.miss
    io.dataHit := dcache.io.hit; io.dataMiss := dcache.io.miss
    io.stallLoadUse := core.io.stallLoadUse; io.stallMemory := core.io.stallMemory
    io.stallMulDiv := core.io.stallMulDiv; io.stallFetch := core.io.stallFetch
    io.stallStoreAck := core.io.stallStoreAck
    io.dataRequestAccepted := core.io.dataRequestAccepted; io.dataRequestOffered := core.io.dataRequestOffered
}
