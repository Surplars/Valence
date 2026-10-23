package soc.core.inorder

import chisel3._
import chisel3.util._

/** One native owner, physically tagged downstream cache. Direct-mapped small TLB; no payload-reset RAM.
  * Lookup/PMP use a registered owner, isolated from EX's address carry and upstream READY.
  * On Sv39 miss, 3-level walker emits read-only PTE requests through the shared physical D-cache.
  * ASIDLEN=0; SFENCE globally invalidates (legal over-fence). Svade faults on clear A/D, no unsafe PTE RMW.
  */
class FiveStageAddressTranslation(p: FiveStageConfig, instruction: Boolean,
    parallelInstructionCandidates: Boolean = false, parallelDataCandidates: Boolean = false,
    registeredInstructionReturn: Boolean = false) extends Module {
    require(p.xlen == 64 || !p.withSv39)
    require(!parallelInstructionCandidates ||
        (instruction && p.fpgaTimingCuts && p.fastInstructionTranslation && p.preparedTranslationProofs))
    require(!parallelDataCandidates ||
        (!instruction && p.fpgaTimingCuts && p.fastDataTranslation && p.preparedTranslationProofs))
    require(!registeredInstructionReturn || (instruction && p.fpgaTimingCuts && p.withC &&
        p.fastInstructionTranslation))
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new FiveStageDataRequest(p)))
        val response = Decoupled(new FiveStageDataResponse(p))
        val physical = new Bundle {
            val request = Decoupled(new FiveStageDataRequest(p))
            val response = Flipped(Decoupled(new FiveStageDataResponse(p)))
        }
        val walk = new Bundle {
            val request = Decoupled(new FiveStageDataRequest(p))
            val response = Flipped(Decoupled(new FiveStageDataResponse(p)))
        }
        val context = Input(new FiveStageTranslationContext(p))
        val entries = Input(Vec(p.pmpEntries, new FiveStagePmpEntry(p)))
        val invalidate = Input(Bool())
        val registeredOwner = Output(Bool())
        val hit = Output(Bool()); val miss = Output(Bool())
        val physicalCacheable = if (instruction && p.fpgaTimingCuts) Some(Output(Bool())) else None
        val addressCandidates = if (parallelInstructionCandidates) Some(Input(Vec(2, UInt(p.xlen.W)))) else None
        val candidateSecond = if (parallelInstructionCandidates) Some(Input(Bool())) else None
        val dataCandidates = if (parallelDataCandidates)
            Some(Input(Vec(2, new FiveStageDataRequest(p)))) else None
        val dataCandidateEarly = if (parallelDataCandidates) Some(Input(Bool())) else None
        val readAhead = if (p.dataReplyHandoff && !instruction) Some(Input(Bool())) else None
        val ordinaryStoreAccepted = if (!instruction) Some(Output(Bool())) else None
    })
    val Seq(idle, lookup, authorize, walkAuthorize, walkSend, walkReceive, walkCheck,
        send, receive, reply, fastHold, authorizeCheck, walkAuthorizeCheck) =
        (if (p.fpgaTimingCuts) (0 until 13).map(i => (BigInt(1) << i).U(13.W)) else Enum(13))
    val stateStorage = RegInit(idle)
    val state = WireDefault(UInt(idle.getWidth.W), stateStorage)
    val nextState = WireDefault(state)
    private def phaseIs(value: UInt, phase: UInt): Bool =
        if (p.fpgaTimingCuts) value(phase.litValue.bitLength - 1) else value === phase
    private def in(phase: UInt): Bool = phaseIs(state, phase)
    if (p.fpgaTimingCuts) when(!reset.asBool) {
        assert(PopCount(stateStorage) === 1.U && PopCount(state) === 1.U,
            "translation phase lost its single existing owner")
    }
    stateStorage := nextState
    val directAccepted = WireDefault(false.B)
    val localWalkNext = if (p.fpgaTimingCuts && p.withSv39)
        Some(WireDefault(VecInit(Seq.fill(3)(false.B)))) else None
    val localWalkEntry = WireDefault(false.B)
    if (p.directFastDataIssue && !instruction) {
        // One bit records a genuine SAME-edge physical handoff. Reconcile
        // the encoded phase locally on the next edge, without adding a
        // receive cycle or sending the saved request a second time.
        val sent = RegNext(directAccepted, false.B)
        when(sent && phaseIs(stateStorage, send)) { state := receive }
    }
    val saved = Reg(new FiveStageDataRequest(p))
    val context = Reg(new FiveStageTranslationContext(p))
    val pa = Reg(UInt(p.xlen.W))
    val result = Reg(new FiveStageDataResponse(p))
    // saved/PA own the physical operation; result owns a separately registered
    // reply. Both payload banks already exist. Only their validity is split.
    val resultPending = if (p.dataReplyHandoff && !instruction) Some(RegInit(false.B)) else None
    // Management-only conservative owner proof, independent of TLB/PMP lookups.
    io.registeredOwner := !phaseIs(stateStorage, idle) || resultPending.getOrElse(false.B)
    when(!reset.asBool) {
        assert(!(io.physical.request.valid || io.walk.request.valid) ||
            io.request.valid || io.registeredOwner,
            "translation request escaped its original offer or registered owner")
    }
    // The cold fault decision must not reset every payload bit. Its existing
    // response owner carries one zero marker; bus-error payloads stay intact.
    val localFaultZero = if (p.fpgaTimingCuts) Some(RegInit(false.B)) else None
    val stale = RegInit(false.B)
    val noAllocate = Reg(Bool())
    val span = if (instruction && p.withC) Some(RegInit(false.B)) else None
    val fastEligible = WireDefault(false.B)
    val fastPa = WireDefault(UInt(p.xlen.W), io.request.bits.address)
    val fastEnabled = if (instruction) p.fastInstructionTranslation else p.fastDataTranslation
    private val stagedPmp = p.fpgaTimingCuts
    private val authorizationReady = if (stagedPmp) in(authorizeCheck) else in(authorize)
    private val walkAuthorizationReady = if (stagedPmp) in(walkAuthorizeCheck) else in(walkAuthorize)
    private def protection(walk: Boolean = false): FiveStagePmp = {
        val checker = Module(new FiveStagePmp(p, registerComparisons = stagedPmp))
        checker.io.capture.foreach(_ := (if (walk) in(walkAuthorize) else in(authorize)))
        checker
    }
    // Two already-existing parcel addresses, NOT two translation owners.
    // Decode their page proofs in parallel before the parcel-state select.
    private val candidates = io.addressCandidates.map(_.toSeq).getOrElse(Seq(io.request.bits.address))
    private val dataCandidates = io.dataCandidates.map(_.toSeq).getOrElse(Seq(io.request.bits))
    private def dataSelect(values: Seq[UInt]): UInt =
        if (parallelDataCandidates) Mux(io.dataCandidateEarly.get, values(1), values(0)) else values.head
    private def equal(a: UInt, b: UInt): Bool =
        if (p.fpgaTimingCuts) I1TimingMath.equal(a, b) else a === b
    private def candidateSelect(values: Seq[UInt]): UInt =
        if (parallelInstructionCandidates) Mux(io.candidateSecond.get, values(1), values(0)) else values.head
    if (parallelInstructionCandidates) when(io.request.valid && !reset.asBool) {
        assert(io.request.bits.address === candidateSelect(candidates),
            "instruction candidate selection contradicts offered address")
    }
    if (parallelDataCandidates) when(io.request.valid && !reset.asBool) {
        assert(io.request.bits.asUInt === dataSelect(dataCandidates.map(_.asUInt)),
            "data translation candidate selection contradicts offered owner")
    }
    val fullPageAllow = WireDefault(false.B)
    val fullPageWriteAllow = WireDefault(false.B)
    val fastNoAllocate = WireDefault(false.B)
    val fastCacheable = WireDefault(if (instruction) false.B else
        I1AddressWindow.contains(io.request.bits.address, p.cacheableBase, p.cacheableBytes))
    val authorizedCacheable = if (instruction && p.fpgaTimingCuts) Some(Reg(Bool())) else None
    val pageAlignedWindow = p.cacheableBase % 4096 == 0 && p.cacheableBytes % 4096 == 0
    val bareFastCacheable = if (instruction && p.fpgaTimingCuts && fastEnabled) Some(Reg(Bool())) else None
    // Full-page PMP success already proves the physical address range.
    // Keep only its physical-width page tag, with an explicit high-bit reject
    // on a later Bare request. A high XLEN alias must never borrow this proof.
    val bareAddressBits = if (p.fpgaTimingCuts) p.physicalBits else p.xlen
    val bareAddressFits = if (bareAddressBits < p.xlen)
        !io.request.bits.address(p.xlen - 1, bareAddressBits).orR else true.B
    val bareFastValid = if (fastEnabled) Some(RegInit(false.B)) else None
    val bareFastPage = if (fastEnabled) Some(Reg(UInt((bareAddressBits - 12).W))) else None
    val bareFastPrivilege = if (fastEnabled) Some(Reg(UInt(2.W))) else None
    val bareWriteValid = if (fastEnabled && !instruction) Some(RegInit(false.B)) else None
    val bareWritePage = if (fastEnabled && !instruction) Some(Reg(UInt((bareAddressBits - 12).W))) else None
    val bareWritePrivilege = if (fastEnabled && !instruction) Some(Reg(UInt(2.W))) else None
    val bareWriteReadable = if (fastEnabled && !instruction) Some(Reg(Bool())) else None
    val currentPrivilege = if (instruction) io.context.privilege else io.context.dataPrivilege
    val savedPrivilege = if (instruction) context.privilege else context.dataPrivilege
    val needsRead = !io.request.bits.write ||
        (io.request.bits.atomic && io.request.bits.atomicOperation =/= 3.U)
    val currentBare = if (p.withSv39) currentPrivilege === 3.U || io.context.satp(63, 60) === 0.U
        else true.B
    val savedBare = if (p.withSv39) savedPrivilege === 3.U || context.satp(63, 60) === 0.U
        else true.B
    // All OFF regions grant M-mode, but never S/U (including MPRV's effective
    // privilege). Require a naturally aligned <=8B interval with no high alias.
    // CSR publishes this exact proof on the same edge as a PMP config change.
    val unrestrictedMachine = p.fpgaTimingCuts.B && currentPrivilege === 3.U && io.context.pmpAllOff
    def machineInterval(address: UInt, size: UInt): Bool = {
        val aligned = MuxLookup(size, false.B)(Seq(0.U -> true.B, 1.U -> !address(0),
            2.U -> !address(1, 0).orR, 3.U -> !address(2, 0).orR))
        val fits = if (p.physicalBits < p.xlen) !address(p.xlen - 1, p.physicalBits).orR else true.B
        unrestrictedMachine && size <= 3.U && aligned && fits
    }
    if (p.pmpEntries > 0) when(unrestrictedMachine && !reset.asBool) {
        assert(!VecInit(io.entries.toSeq.map(_.config(4, 3).orR)).asUInt.orR,
            "unrestricted M-mode must not bypass an active PMP region")
    }
    if (fastEnabled) {
        val pagePmp = protection()
        pagePmp.io.entries := io.entries
        pagePmp.io.address := (pa >> 12) << 12; pagePmp.io.size := 12.U
        pagePmp.io.privilege := savedPrivilege
        pagePmp.io.execute := instruction.B; pagePmp.io.write := false.B
        fullPageAllow := pagePmp.io.allow
        if (!instruction) {
            val pageWritePmp = protection()
            pageWritePmp.io.entries := io.entries
            pageWritePmp.io.address := (pa >> 12) << 12; pageWritePmp.io.size := 12.U
            pageWritePmp.io.privilege := savedPrivilege
            pageWritePmp.io.execute := false.B; pageWritePmp.io.write := true.B
            fullPageWriteAllow := pageWritePmp.io.allow
            fastNoAllocate := io.request.bits.noAllocate ||
                (io.request.bits.write && !bareWriteReadable.get)
        }
        val readMatch = bareFastValid.get &&
            bareFastPrivilege.get === currentPrivilege &&
            equal(bareFastPage.get, io.request.bits.address(bareAddressBits - 1, 12))
        val barePermission = if (instruction) readMatch else Mux(io.request.bits.write,
            bareWriteValid.get && bareWritePrivilege.get === currentPrivilege &&
                equal(bareWritePage.get, io.request.bits.address(bareAddressBits - 1, 12)) &&
                (!needsRead || bareWriteReadable.get), readMatch)
        fastEligible := currentBare && ((bareAddressFits && barePermission) ||
            machineInterval(io.request.bits.address, io.request.bits.size))
        if (parallelDataCandidates) {
            val prepared = dataCandidates.map { request =>
                val fits = if (bareAddressBits < p.xlen) !request.address(p.xlen - 1, bareAddressBits).orR else true.B
                val needsRead = !request.write || (request.atomic && request.atomicOperation =/= 3.U)
                val read = bareFastValid.get && bareFastPrivilege.get === currentPrivilege &&
                    equal(bareFastPage.get, request.address(bareAddressBits - 1, 12))
                val write = bareWriteValid.get && bareWritePrivilege.get === currentPrivilege &&
                    equal(bareWritePage.get, request.address(bareAddressBits - 1, 12)) &&
                    (!needsRead || bareWriteReadable.get)
                (fits && Mux(request.write, write, read)) || machineInterval(request.address, request.size)
            }
            fastEligible := currentBare && dataSelect(prepared.map(_.asUInt)).asBool
            fastPa := dataSelect(dataCandidates.map(_.address))
            fastCacheable := dataSelect(dataCandidates.map(request =>
                I1AddressWindow.contains(request.address, p.cacheableBase, p.cacheableBytes).asUInt)).asBool
            fastNoAllocate := io.request.bits.noAllocate ||
                (io.request.bits.write && !unrestrictedMachine && !bareWriteReadable.get)
        } else if (!instruction) {
            fastNoAllocate := io.request.bits.noAllocate ||
                (io.request.bits.write && !unrestrictedMachine && !bareWriteReadable.get)
        }
        if (parallelInstructionCandidates) {
            val bareGrants = candidates.map { address =>
                val fits = if (bareAddressBits < p.xlen) !address(p.xlen - 1, bareAddressBits).orR else true.B
                (fits && bareFastValid.get && bareFastPrivilege.get === currentPrivilege &&
                    equal(bareFastPage.get, address(bareAddressBits - 1, 12))) ||
                    machineInterval(address, io.request.bits.size)
            }
            fastEligible := currentBare && candidateSelect(bareGrants).asBool
            fastPa := candidateSelect(candidates)
        }
        if (instruction && p.fpgaTimingCuts) {
            val barePhysicalCacheable = candidateSelect(candidates.map(a =>
                I1AddressWindow.contains(a, p.cacheableBase, p.cacheableBytes))).asBool
            fastCacheable := !io.request.bits.noAllocate && (if (pageAlignedWindow)
                Mux(unrestrictedMachine, barePhysicalCacheable, bareFastCacheable.get)
                else barePhysicalCacheable)
            if (parallelInstructionCandidates && !pageAlignedWindow) {
                fastCacheable := !io.request.bits.noAllocate &&
                    candidateSelect(candidates.map(a => I1AddressWindow.contains(
                        a, p.cacheableBase, p.cacheableBytes))).asBool
            }
        }
        when(authorizationReady && savedBare && !stale && !io.invalidate) {
            if (instruction) {
                when(fullPageAllow) {
                    bareFastValid.get := true.B; bareFastPage.get := pa(bareAddressBits - 1, 12)
                    bareFastPrivilege.get := savedPrivilege
                    bareFastCacheable.foreach(_ := I1AddressWindow.contains(pa, p.cacheableBase, p.cacheableBytes))
                }
            } else {
                // Independent read/write proof tags prevent source/destination
                // page ping-pong. These are permissions, not extra data owners.
                when(saved.write) {
                    bareWriteValid.get := fullPageWriteAllow
                    bareWritePage.get := pa(bareAddressBits - 1, 12); bareWritePrivilege.get := savedPrivilege
                    bareWriteReadable.get := fullPageAllow
                }.otherwise {
                    bareFastValid.get := fullPageAllow; bareFastPage.get := pa(bareAddressBits - 1, 12)
                    bareFastPrivilege.get := savedPrivilege
                }
            }
        }
        when(io.invalidate) { bareFastValid.get := false.B; bareWriteValid.foreach(_ := false.B) }
    }
    val effective = if (instruction) context.privilege else context.dataPrivilege
    val pmp = protection()
    pmp.io.entries := io.entries; pmp.io.address := pa
    pmp.io.size := saved.size; pmp.io.privilege := effective
    pmp.io.execute := instruction.B; pmp.io.write := saved.write
    val atomicReadAllowed = WireDefault(true.B)
    if (p.withA && !instruction) {
        val readPmp = protection()
        readPmp.io.entries := io.entries; readPmp.io.address := pa; readPmp.io.size := saved.size
        readPmp.io.privilege := effective; readPmp.io.execute := false.B; readPmp.io.write := false.B
        atomicReadAllowed := !saved.atomic || saved.atomicOperation === 2.U ||
            saved.atomicOperation === 3.U || readPmp.io.allow
    }
    val wordExecuteAllowed = WireDefault(false.B)
    if (instruction && p.withC) {
        val wordPmp = protection()
        wordPmp.io.entries := io.entries
        wordPmp.io.address := (pa >> log2Ceil(p.xlen / 8)) << log2Ceil(p.xlen / 8)
        wordPmp.io.size := log2Ceil(p.xlen / 8).U; wordPmp.io.privilege := effective
        wordPmp.io.execute := true.B; wordPmp.io.write := false.B
        wordExecuteAllowed := wordPmp.io.allow
    }
    val linePmp = protection()
    linePmp.io.entries := io.entries
    linePmp.io.address := (pa >> log2Ceil(p.cacheLineBytes)) << log2Ceil(p.cacheLineBytes)
    linePmp.io.size := log2Ceil(p.cacheLineBytes).U
    linePmp.io.privilege := effective; linePmp.io.execute := instruction.B; linePmp.io.write := false.B
    // One owner, with optional consume-and-replace at the REGISTERED reply
    // boundary. Never connect admission to physical response VALID/READY.
    val readHandoff = if (p.dataReplyHandoff && !instruction) {
        val aligned = MuxLookup(io.request.bits.size, false.B)(Seq(
            0.U -> true.B, 1.U -> !io.request.bits.address(0),
            2.U -> !io.request.bits.address(1, 0).orR, 3.U -> !io.request.bits.address(2, 0).orR))
        in(receive) && io.physical.response.fire && !io.physical.response.bits.error &&
            !io.physical.response.bits.pageFault && fastEligible &&
            fastCacheable &&
            !fastNoAllocate && !io.invalidate && !io.request.bits.write &&
            !io.request.bits.atomic && aligned
    } else false.B
    val normalSlot = (in(idle) && !resultPending.getOrElse(false.B)) ||
        (p.overlapDataRetirement.B && !instruction.B && in(reply) && io.response.ready)
    val requestSlot = Mux(io.readAhead.getOrElse(false.B), readHandoff, normalSlot)
    io.request.ready := requestSlot
    io.ordinaryStoreAccepted.foreach { accepted =>
        // A handoff is read-only. Factor the exact ordinary-store acceptance
        // locally so its reservation-clear event never traverses readHandoff's
        // address/permission proof. Request READY and every acceptance edge stay unchanged.
        accepted := io.request.valid && io.request.bits.write && !io.request.bits.atomic &&
            !io.readAhead.getOrElse(false.B) && normalSlot
        when(!reset.asBool) {
            assert(accepted === (io.request.fire && io.request.bits.write && !io.request.bits.atomic),
                "factored ordinary-store admission changed accepted store ownership")
        }
    }
    io.response.valid := resultPending.getOrElse(in(reply))
    io.response.bits := result
    localFaultZero.foreach(zero => io.response.bits.data := Mux(zero, 0.U, result.data))
    io.physical.request.valid := in(send)
    io.physical.request.bits := saved
    io.physical.request.bits.address := pa
    // A legal scalar access near a PMP boundary must not speculatively fill prohibited neighbours.
    io.physical.request.bits.noAllocate := noAllocate
    io.physicalCacheable.foreach(_ := Mux(in(send) || in(fastHold),
        authorizedCacheable.get, fastCacheable))
    io.physical.response.ready := in(receive) &&
        (!resultPending.getOrElse(false.B) || io.response.ready)
    resultPending.foreach { pending => when(io.response.fire) { pending := false.B } }
    io.walk.request.valid := false.B
    io.walk.request.bits := 0.U.asTypeOf(new FiveStageDataRequest(p))
    io.walk.response.ready := false.B
    io.hit := false.B; io.miss := false.B
    def fail(page: Bool): Unit = {
        resultPending.foreach(_ := true.B)
        if (p.fpgaTimingCuts) { localFaultZero.get := true.B } else { result.data := 0.U }
        result.error := true.B; result.pageFault := page
        result.fetchSpan := false.B; result.parcelClasses.foreach(_ := 0.U); nextState := reply
    }
    if (p.fpgaTimingCuts) {
        // These payload registers are unowned in idle, and an old IF receive
        // or registered data reply consumes result/span, not saved/context/PA.
        // Prepare independently of upstream VALID and downstream READY. The
        // phase/authorization below remains the sole ownership commit.
        val payloadFree = in(idle) ||
            ((instruction && fastEnabled).B && in(receive)) ||
            ((p.overlapDataRetirement && !instruction).B && in(reply)) ||
            ((p.dataReplyHandoff && !instruction).B && in(receive))
        when(payloadFree) {
            saved := io.request.bits
            context := io.context
            // Permission decides ownership/state, not the PA payload mux.
            // A slow Sv39 lookup/walk replaces this speculative PA before
            // authorization. Bare fastPa is the original offered address.
            pa := fastPa
            authorizedCacheable.foreach(_ := fastCacheable)
        }
    }
    when(io.request.fire) {
        if (!p.fpgaTimingCuts) {
            saved := io.request.bits; context := io.context
            pa := io.request.bits.address
        }
        stale := io.invalidate
        nextState := lookup
    }
    when(io.invalidate && !in(idle)) { stale := true.B }
    if (stagedPmp) {
        when(in(authorize)) { nextState := authorizeCheck }
        when(in(walkAuthorize)) { nextState := walkAuthorizeCheck }
    }
    when(authorizationReady) {
        authorizedCacheable.foreach(_ := !saved.noAllocate && linePmp.io.allow &&
            I1AddressWindow.contains(pa, p.cacheableBase, p.cacheableBytes))
        when(!pmp.io.allow || !atomicReadAllowed) { fail(false.B) }.otherwise {
            noAllocate := saved.noAllocate || !linePmp.io.allow; nextState := send
            span.foreach(_ := wordExecuteAllowed)
        }
    }
    when(io.physical.request.fire) { nextState := receive }
    when(io.physical.response.fire) {
        resultPending.foreach(_ := true.B)
        if (!p.fpgaTimingCuts) { result := io.physical.response.bits }
        result.fetchSpan := span.getOrElse(false.B); nextState := reply
    }
    if (p.fpgaTimingCuts) when(!resultPending.getOrElse(in(reply)) || io.response.ready) {
        // Unowned data may prepare outside receive; a visible registered
        // reply MUST hold. Fault/status ownership remains separately gated.
        result.data := io.physical.response.bits.data
        result.parcelClasses.foreach(_ := io.physical.response.bits.parcelClasses.get)
    }
    if (p.fpgaTimingCuts) when(in(receive) &&
        (!resultPending.getOrElse(false.B) || io.response.ready)) {
        // Invalid cycles carry unowned payload. Only the genuine response
        // fire publishes reply; do not put cache VALID/READY in a 64-bit
        // RAM-return data/enable mux ahead of these existing registers.
        result.error := io.physical.response.bits.error
        result.pageFault := io.physical.response.bits.pageFault
        localFaultZero.get := false.B
        result.fetchSpan := span.getOrElse(false.B)
    }
    if (p.fpgaTimingCuts) {
        // Retiring a reply may only change this phase's idle/reply/lookup
        // bits. Do not distribute EX-dependent response READY as a clear of
        // every unrelated PTW phase register.
        when(in(reply)) {
            nextState := Mux(io.request.fire, lookup, Mux(io.response.ready, idle, reply))
        }
    } else when(io.response.fire && !io.request.fire) { nextState := idle }
    if (!p.withSv39) {
        when(in(lookup)) { nextState := authorize }
    } else {
        val indexBits = log2Ceil(p.tlbEntries)
        val valid = RegInit(0.U(p.tlbEntries.W))
        val tags = Reg(Vec(p.tlbEntries, UInt(27.W)))
        val ppns = Reg(Vec(p.tlbEntries, UInt((p.physicalBits - 12).W)))
        val levels = Reg(Vec(p.tlbEntries, UInt(2.W)))
        val permissions = Reg(Vec(p.tlbEntries, UInt(8.W)))
        val fastPage = if (fastEnabled) Some(RegInit(0.U(p.tlbEntries.W))) else None
        val fastWritePage = if (fastEnabled && !instruction) Some(RegInit(0.U(p.tlbEntries.W))) else None
        val fastReadTag = if (fastEnabled && !instruction) Some(Reg(Vec(p.tlbEntries, UInt(27.W)))) else None
        val fastWriteTag = if (fastEnabled && !instruction) Some(Reg(Vec(p.tlbEntries, UInt(27.W)))) else None
        val fastWriteReadable = if (fastEnabled && !instruction) Some(RegInit(0.U(p.tlbEntries.W))) else None
        // These are the physical page covered by each existing proof, not new
        // translations/slots. Resolve superpage low PPN bits at authorization,
        // rather than repeating level-dependent PA assembly on every demand.
        val fastReadPhysicalPage = if (fastEnabled && (!instruction || p.fpgaTimingCuts))
            Some(Reg(Vec(p.tlbEntries, UInt((p.physicalBits - 12).W)))) else None
        val fastInstructionCacheable = if (fastEnabled && instruction && p.fpgaTimingCuts)
            Some(Reg(Vec(p.tlbEntries, Bool()))) else None
        val indexedInstructionProof = fastEnabled && instruction && p.fpgaTimingCuts && p.preparedTranslationProofs
        val indexedDataProof = fastEnabled && !instruction && p.indexedDataProofs
        // Bind the SAME read/write full-page proof slots to their real TLB
        // owners. Only the VPN index selects a physical payload; tag/superpage
        // permission controls admission, never the D-cache SRAM address.
        val dataReadOwner = if (indexedDataProof) Some(Reg(Vec(p.tlbEntries, UInt(indexBits.W)))) else None
        val dataWriteOwner = if (indexedDataProof) Some(Reg(Vec(p.tlbEntries, UInt(indexBits.W)))) else None
        // Bank-local permission preparation copies only the owning entry's
        // flags into its existing full-page proof. Ownership still comes from
        // the source row and its replacement/invalidation mask. Dynamic
        // privilege/SUM/MXR are checked on every offer, never cached as a grant.
        val dataReadProofFlags = if (indexedDataProof && p.bankedTlbProofs)
            Some(Reg(Vec(p.tlbEntries, UInt(8.W)))) else None
        val dataWriteProofFlags = if (indexedDataProof && p.bankedTlbProofs)
            Some(Reg(Vec(p.tlbEntries, UInt(8.W)))) else None
        // Re-index the EXISTING full-page proof slots, not new TLB entries.
        // The source row binding invalidates proofs on replacement; a new
        // row0 mapping invalidates all proof slots because it may dominate
        // any leaf row. Payload uses only the offered VPN index, while full
        // tag/permission/source ownership still controls actual acceptance.
        val instructionProofTags = if (indexedInstructionProof)
            Some(Reg(Vec(p.tlbEntries, UInt(27.W)))) else None
        val instructionProofFlags = if (indexedInstructionProof)
            Some(Reg(Vec(p.tlbEntries, UInt(8.W)))) else None
        val instructionProofOwner = if (indexedInstructionProof)
            Some(Reg(Vec(p.tlbEntries, UInt(indexBits.W)))) else None
        val fastWritePhysicalPage = if (fastEnabled && !instruction)
            Some(Reg(Vec(p.tlbEntries, UInt((p.physicalBits - 12).W)))) else None
        val vpn = saved.address(38, 12)
        def smallIndex(v: UInt): UInt = v(indexBits - 1, 0) ^ v(2 * indexBits - 1, indexBits)
        // With bank mode explicitly selected, all PA/permission payloads are
        // prepared in <=8-row groups. Only completed group results see the
        // high index. No tag, source permission, or candidate-owner decision
        // enters the PA selection cone. The default <=8 implementation is
        // unchanged; the 16/32 generic fallback remains available flag-off.
        def bankSelect(index: UInt, values: Seq[UInt]): UInt = {
            require(p.bankedTlbProofs && values.size == p.tlbEntries)
            val localIndex = index(2, 0)
            val bankIndex = index(indexBits - 1, 3)
            val localRows = (0 until 8).map(i => localIndex === i.U)
            val banks = values.grouped(8).toSeq.zipWithIndex.map { case (group, bank) =>
                val selected = WireDefault(Mux1H(localRows.zip(group)))
                selected.suggestName(s"proofBank${bank}Payload")
                selected
            }
            Mux1H(banks.zipWithIndex.map { case (value, bank) => (bankIndex === bank.U) -> value })
        }
        def proofSelect(index: UInt, rows: Seq[Bool], values: Seq[UInt]): UInt =
            if (p.bankedTlbProofs) bankSelect(index, values) else Mux1H(rows.zip(values))
        def proofGranted(index: UInt, grants: Seq[Bool]): Bool =
            if (p.bankedTlbProofs) bankSelect(index, grants.map(_.asUInt)).asBool else grants.reduce(_ || _)
        def superHit(v: UInt): Bool = valid(0) && (
            (levels(0) === 2.U && equal(tags(0)(26, 18), v(26, 18))) ||
            (levels(0) === 1.U && equal(tags(0)(26, 9), v(26, 9))))
        // Entry zero can cover a REAL 2MiB/1GiB mapping. No added entry or 4-way XLEN CAM:
        // one short 9/18-bit prefix check, or the existing direct-mapped 4KiB tag lookup.
        val superPageHit = superHit(vpn)
        val leafIndex = smallIndex(vpn)
        val index = Mux(superPageHit, 0.U, leafIndex)
        // Resolve the ordinary leaf independently of the dominant superpage.
        // Superpage hit must not select a wide tag/permission mux before the
        // lookup phase can decide miss/fault. Entry-zero precedence is retained.
        val tlbHit = (superPageHit || (valid(leafIndex) && equal(tags(leafIndex), vpn))) && !stale
        val level = Reg(UInt(2.W))
        val table = Reg(UInt(p.xlen.W))
        val pte = Reg(UInt(64.W))
        val walkAddress = Reg(UInt(p.xlen.W))
        val walkNoAllocate = Reg(Bool())
        val translated = effective =/= 3.U && context.satp(63, 60) === 8.U
        val canonical = saved.address(63, 39) === Fill(25, saved.address(38))
        def permitted(flags: UInt): Bool = {
            val rwx = if (instruction) flags(3) else Mux(saved.write, flags(2),
                flags(1) || (context.mxr && flags(3)))
            val user = Mux(effective === 0.U, flags(4),
                !flags(4) || (!instruction.B && context.sum))
            rwx && user && flags(6) && (!saved.write || flags(7))
        }
        val lookupPermitted = if (p.fpgaTimingCuts) {
            val grants = (0 until p.tlbEntries).map(i => permitted(permissions(i)))
            val leafGrant = if (p.bankedTlbProofs) bankSelect(leafIndex, grants.map(_.asUInt)).asBool
                else Mux1H((0 until p.tlbEntries).map(i => (leafIndex === i.U) -> grants(i)))
            Mux(superPageHit, grants.head, leafGrant)
        } else permitted(permissions(index))
        def physical(ppn: UInt, lev: UInt): UInt = Cat(ppn, saved.address(11, 0)) |
            Mux(lev === 2.U, saved.address(29, 12) << 12,
                Mux(lev === 1.U, saved.address(20, 12) << 12, 0.U))
        if (p.fpgaTimingCuts) {
            // Free walker payload, prepared before hit/miss/permission decides
            // ownership. No tag -> hit -> 40-bit table CE or level CE.
            // Leaf/fault paths never use this table; a new walk always reloads
            // its own root. Non-leaf descent still uses the OLD level/PA here.
            when(in(lookup)) {
                table := context.satp(p.physicalBits - 13, 0) << 12
                level := 2.U
            }
            when(in(walkCheck)) {
                table := pte(53, 10) << 12
                level := level - 1.U
            }
            // Lookup/fault permission owns the PHASE, not this free payload.
            // A miss or rejected PTE cannot reach authorize/send and will
            // overwrite this value before any physical request is offered.
            when(in(lookup) && translated) { pa := physical(ppns(index), levels(index)) }
            when(in(walkCheck)) { pa := physical(pte(53, 10), level) }
        }
        if (fastEnabled) {
            val fv = io.request.bits.address(38, 12)
            val fi = Mux(superHit(fv), 0.U, smallIndex(fv))
            val fp = permissions(fi)
            val canonicalFast = io.request.bits.address(63, 39) === Fill(25, io.request.bits.address(38))
            val userFast = Mux(currentPrivilege === 0.U, fp(4),
                !fp(4) || (!instruction.B && io.context.sum))
            val requestedRwx = if (instruction) fp(3)
                else Mux(io.request.bits.write, fp(2), fp(1) || (io.context.mxr && fp(3)))
            // A D proof has its OWN exact full VPN tag and is cleared on every
            // replacement/invalidation of its owning TLB entry. Rechecking the
            // generic superpage tag is redundant, not an additional permission.
            val entryMatch = if (instruction) tags(fi) === fv else true.B
            val pagePermission = if (instruction) fastPage.get(fi) else Mux(io.request.bits.write,
                fastWritePage.get(fi) && fastWriteTag.get(fi) === fv &&
                    (!needsRead || fastWriteReadable.get(fi)),
                fastPage.get(fi) && fastReadTag.get(fi) === fv)
            when(!currentBare && io.context.satp(63, 60) === 8.U) {
                fastEligible := io.context.satp(63, 60) === 8.U && canonicalFast &&
                    valid(fi) && entryMatch && pagePermission &&
                    requestedRwx && fp(6) && (!io.request.bits.write || fp(7)) && userFast
                if (instruction && p.fpgaTimingCuts) {
                    if (p.preparedTranslationProofs) {
                        // No full tag match may precede the I-cache RAM address.
                        // Existing proof capacity stays tlbEntries; source bindings
                        // and replacement invalidation retain real TLB authority.
                        val prepared = candidates.map { address =>
                            val vpn = address(38, 12)
                            val proofIndex = smallIndex(vpn)
                            val rows = (0 until p.tlbEntries).map(i => proofIndex === i.U)
                            val grants = rows.zipWithIndex.map { case (row, i) =>
                                val source = instructionProofOwner.get(i)
                                val hit = (if (p.bankedTlbProofs) true.B else row) && fastPage.get(i) &&
                                    (if (p.bankedTlbProofs) true.B else valid(source)) &&
                                    equal(instructionProofTags.get(i), vpn)
                                val flags = instructionProofFlags.get(i)
                                val user = Mux(currentPrivilege === 0.U, flags(4), !flags(4))
                                hit && flags(3) && flags(6) && user
                            }
                            val eligible = address(63, 39) === Fill(25, address(38)) && proofGranted(proofIndex, grants)
                            val physical = Cat(proofSelect(proofIndex, rows, fastReadPhysicalPage.get.toSeq), address(11, 0))
                            val cacheable = if (pageAlignedWindow)
                                proofSelect(proofIndex, rows, fastInstructionCacheable.get.toSeq.map(_.asUInt)).asBool
                                else I1AddressWindow.contains(physical, p.cacheableBase, p.cacheableBytes)
                            when(io.request.valid && eligible && !reset.asBool) {
                                val source = instructionProofOwner.get(proofIndex)
                                val sourcePhysical = Cat(ppns(source), address(11, 0)) |
                                    Mux(levels(source) === 2.U, address(29, 12) << 12,
                                        Mux(levels(source) === 1.U, address(20, 12) << 12, 0.U))
                                assert(valid(source) && physical === sourcePhysical &&
                                    instructionProofFlags.get(proofIndex) === permissions(source),
                                    "indexed instruction proof lost its live TLB mapping/permissions")
                                assert(source === 0.U || !superHit(vpn),
                                    "a new dominant superpage failed to invalidate a leaf proof")
                            }
                            (eligible, physical, cacheable)
                        }
                        fastEligible := io.context.satp(63, 60) === 8.U &&
                            candidateSelect(prepared.map(_._1)).asBool
                        fastPa := candidateSelect(prepared.map(_._2))
                        fastCacheable := !io.request.bits.noAllocate &&
                            candidateSelect(prepared.map(_._3)).asBool
                    } else {
                        // Larger configurations keep an indexed proof mux rather
                        // than growing an unbounded fast-path associative lookup.
                        fastPa := Cat(fastReadPhysicalPage.get(fi), io.request.bits.address(11, 0))
                        fastCacheable := !io.request.bits.noAllocate && (if (pageAlignedWindow)
                            fastInstructionCacheable.get(fi) else
                            I1AddressWindow.contains(fastPa, p.cacheableBase, p.cacheableBytes))
                    }
                } else if (instruction) {
                    fastPa := Cat(ppns(fi), io.request.bits.address(11, 0)) |
                        Mux(levels(fi) === 2.U, io.request.bits.address(29, 12) << 12,
                            Mux(levels(fi) === 1.U, io.request.bits.address(20, 12) << 12, 0.U))
                } else if (parallelDataCandidates || indexedDataProof) {
                    // Both EXISTING ADDR/MEM addresses are prepared in
                    // parallel. Late backend occupancy chooses only the
                    // boolean/PA result; it does not precede a TLB index mux.
                    // Predecode permissions per real TLB source before the
                    // proof-owner mux. A late read/write decision must not
                    // select a source, then flags, then permission logic.
                    val sourceRead = VecInit((0 until p.tlbEntries).map { source =>
                        val flags = permissions(source)
                        val user = Mux(currentPrivilege === 0.U, flags(4), !flags(4) || io.context.sum)
                        valid(source) && (flags(1) || (io.context.mxr && flags(3))) && user && flags(6)
                    })
                    val sourceWrite = VecInit((0 until p.tlbEntries).map { source =>
                        val flags = permissions(source)
                        val user = Mux(currentPrivilege === 0.U, flags(4), !flags(4) || io.context.sum)
                        valid(source) && flags(2) && user && flags(6) && flags(7)
                    })
                    val prepared = dataCandidates.map { request =>
                        val v = request.address(38, 12)
                        val dominant = superHit(v)
                        val leafIndex = smallIndex(v)
                        val rows = (0 until p.tlbEntries).map { i =>
                            if (indexedDataProof) leafIndex === i.U
                            else if (i == 0) dominant || leafIndex === 0.U
                            else !dominant && leafIndex === i.U
                        }
                        val needsRead = !request.write ||
                            (request.atomic && request.atomicOperation =/= 3.U)
                        val grants = rows.zipWithIndex.map { case (row, i) =>
                            val readSource = if (indexedDataProof) dataReadOwner.get(i) else i.U
                            val writeSource = if (indexedDataProof) dataWriteOwner.get(i) else i.U
                            val read = fastPage.get(i) && equal(fastReadTag.get(i), v)
                            val write = fastWritePage.get(i) && equal(fastWriteTag.get(i), v) &&
                                (!needsRead || fastWriteReadable.get(i))
                            val readAllowed = if (p.bankedTlbProofs) {
                                val flags = dataReadProofFlags.get(i)
                                val user = Mux(currentPrivilege === 0.U, flags(4), !flags(4) || io.context.sum)
                                (flags(1) || (io.context.mxr && flags(3))) && user && flags(6)
                            } else sourceRead(readSource)
                            val writeAllowed = if (p.bankedTlbProofs) {
                                val flags = dataWriteProofFlags.get(i)
                                val user = Mux(currentPrivilege === 0.U, flags(4), !flags(4) || io.context.sum)
                                flags(2) && user && flags(6) && flags(7)
                            } else sourceWrite(writeSource)
                            (if (p.bankedTlbProofs) true.B else row) &&
                                Mux(request.write, write && writeAllowed, read && readAllowed)
                        }
                        val canonical = equal(request.address(63, 39), Fill(25, request.address(38)))
                        val physicalPage = proofSelect(leafIndex, rows, (0 until p.tlbEntries).map { i =>
                            Mux(request.write, fastWritePhysicalPage.get(i), fastReadPhysicalPage.get(i))
                        })
                        val readable = proofSelect(leafIndex, rows, fastWriteReadable.get.asBools.map(_.asUInt)).asBool
                        // The board window is page aligned. Compare each
                        // EXISTING physical proof page in parallel, before
                        // its VPN-index selection, not after PA assembly.
                        // Non-page-aligned parameterizations keep exact PA
                        // qualification rather than widening their window.
                        val cacheable = if (pageAlignedWindow) proofSelect(leafIndex, rows, (0 until p.tlbEntries).map { i =>
                            val read = I1AddressWindow.contains((fastReadPhysicalPage.get(i) << 12).pad(p.xlen),
                                p.cacheableBase, p.cacheableBytes)
                            val write = I1AddressWindow.contains((fastWritePhysicalPage.get(i) << 12).pad(p.xlen),
                                p.cacheableBase, p.cacheableBytes)
                            Mux(request.write, write, read).asUInt
                        }).asBool else I1AddressWindow.contains(Cat(physicalPage, request.address(11, 0)),
                            p.cacheableBase, p.cacheableBytes)
                        if (indexedDataProof) when(io.request.valid && canonical && proofGranted(leafIndex, grants) &&
                            !reset.asBool) {
                            val source = Mux(request.write, dataWriteOwner.get(leafIndex),
                                dataReadOwner.get(leafIndex))
                            val originalPhysical = Cat(ppns(source), request.address(11, 0)) |
                                Mux(levels(source) === 2.U, request.address(29, 12) << 12,
                                    Mux(levels(source) === 1.U, request.address(20, 12) << 12, 0.U))
                            assert(valid(source) && Cat(physicalPage, request.address(11, 0)) === originalPhysical,
                                "indexed data proof lost its live physical TLB mapping")
                            if (p.bankedTlbProofs) {
                                val flags = Mux(request.write, dataWriteProofFlags.get(leafIndex),
                                    dataReadProofFlags.get(leafIndex))
                                assert(flags === permissions(source),
                                    "banked data proof lost its live source permissions")
                            }
                            assert(source === 0.U || !superHit(v),
                                "dominant superpage failed to invalidate a data leaf proof")
                        }
                        (canonical && proofGranted(leafIndex, grants), Cat(physicalPage, request.address(11, 0)),
                            request.noAllocate || (request.write && !readable), cacheable)
                    }
                    fastEligible := dataSelect(prepared.map(_._1.asUInt)).asBool
                    fastPa := dataSelect(prepared.map(_._2))
                    fastNoAllocate := dataSelect(prepared.map(_._3.asUInt)).asBool
                    fastCacheable := dataSelect(prepared.map(_._4.asUInt)).asBool
                } else {
                    fastPa := Cat(Mux(io.request.bits.write, fastWritePhysicalPage.get(fi),
                        fastReadPhysicalPage.get(fi)), io.request.bits.address(11, 0))
                    fastNoAllocate := io.request.bits.noAllocate ||
                        (io.request.bits.write && !fastWriteReadable.get(fi))
                    fastCacheable := I1AddressWindow.contains(fastPa, p.cacheableBase, p.cacheableBytes)
                }
            }
            when(authorizationReady && !savedBare && context.satp(63, 60) === 8.U &&
                !stale && !io.invalidate) {
                // Fast authorization covers ONLY this specific 4KiB slice, not the whole superpage.
                // Its high VPN prefix is unchanged, so the superpage match remains valid.
                val mask = UIntToOH(index, p.tlbEntries)
                if (instruction) {
                    when(valid(index) && levels(index) =/= 0.U) { tags(index) := vpn }
                    val proofIndex = if (indexedInstructionProof) smallIndex(vpn) else index
                    val proofMask = UIntToOH(proofIndex, p.tlbEntries)
                    instructionProofTags.foreach(_(proofIndex) := vpn)
                    instructionProofFlags.foreach(_(proofIndex) := permissions(index))
                    instructionProofOwner.foreach(_(proofIndex) := index)
                    fastReadPhysicalPage.foreach(_(proofIndex) := pa(p.physicalBits - 1, 12))
                    fastInstructionCacheable.foreach(_(proofIndex) :=
                        I1AddressWindow.contains(pa, p.cacheableBase, p.cacheableBytes))
                    fastPage.get := Mux(fullPageAllow, fastPage.get | proofMask, fastPage.get & ~proofMask)
                } else {
                    val proofIndex = if (indexedDataProof) smallIndex(vpn) else index
                    val proofMask = UIntToOH(proofIndex, p.tlbEntries)
                    when(saved.write) {
                        fastWriteTag.get(proofIndex) := vpn
                        fastWritePhysicalPage.get(proofIndex) := pa(p.physicalBits - 1, 12)
                        dataWriteOwner.foreach(_(proofIndex) := index)
                        dataWriteProofFlags.foreach(_(proofIndex) := permissions(index))
                        fastWritePage.get := Mux(fullPageWriteAllow,
                            fastWritePage.get | proofMask, fastWritePage.get & ~proofMask)
                        fastWriteReadable.get := Mux(fullPageAllow,
                            fastWriteReadable.get | proofMask, fastWriteReadable.get & ~proofMask)
                    }.otherwise {
                        fastReadTag.get(proofIndex) := vpn
                        fastReadPhysicalPage.get(proofIndex) := pa(p.physicalBits - 1, 12)
                        dataReadOwner.foreach(_(proofIndex) := index)
                        dataReadProofFlags.foreach(_(proofIndex) := permissions(index))
                        fastPage.get := Mux(fullPageAllow, fastPage.get | proofMask, fastPage.get & ~proofMask)
                    }
                }
            }
            when(io.invalidate) { fastPage.get := 0.U; fastWritePage.foreach(_ := 0.U) }
        }
        val walkVpn = MuxLookup(level, vpn(8, 0))(Seq(2.U -> vpn(26, 18), 1.U -> vpn(17, 9)))
        val pteAddress = table | (walkVpn << 3)
        val walkPmp = protection(walk = true)
        val walkLine = protection(walk = true)
        for (checker <- Seq(walkPmp, walkLine)) {
            checker.io.entries := io.entries; checker.io.privilege := 1.U
            checker.io.execute := false.B; checker.io.write := false.B
        }
        walkPmp.io.address := pteAddress; walkPmp.io.size := 3.U
        walkLine.io.address := (pteAddress >> log2Ceil(p.cacheLineBytes)) << log2Ceil(p.cacheLineBytes)
        walkLine.io.size := log2Ceil(p.cacheLineBytes).U
        io.walk.request.valid := in(walkSend)
        io.walk.request.bits.address := walkAddress; io.walk.request.bits.size := 3.U
        io.walk.request.bits.noAllocate := walkNoAllocate
        io.walk.response.ready := in(walkReceive)
        localWalkNext.foreach { bits =>
            val waiting = phaseIs(stateStorage, walkSend)
            val returning = phaseIs(stateStorage, walkReceive)
            bits(0) := (waiting && !io.walk.request.ready) ||
                (phaseIs(stateStorage, walkAuthorizeCheck) && walkPmp.io.allow)
            bits(1) := (waiting && io.walk.request.ready) ||
                (returning && !io.walk.response.valid)
            bits(2) := returning && io.walk.response.valid && !io.walk.response.bits.error
        }
        when(in(lookup)) {
            when(!translated) { nextState := authorize }
                .elsewhen(!canonical) { fail(true.B) }
                .elsewhen(tlbHit) {
                    io.hit := true.B
                    when(!lookupPermitted) { fail(true.B) }.otherwise {
                        if (!p.fpgaTimingCuts) { pa := physical(ppns(index), levels(index)) }
                        nextState := authorize
                    }
                }.otherwise {
                    io.miss := true.B
                    if (!p.fpgaTimingCuts) {
                        level := 2.U
                        table := context.satp(p.physicalBits - 13, 0) << 12
                    }
                    nextState := walkAuthorize
                }
        }
        when(walkAuthorizationReady) {
            when(!walkPmp.io.allow) { fail(false.B) }.otherwise {
                walkAddress := pteAddress; walkNoAllocate := !walkLine.io.allow; nextState := walkSend
            }
        }
        when(io.walk.request.fire) { nextState := walkReceive }
        if (p.fpgaTimingCuts) when(!in(walkCheck)) { pte := io.walk.response.bits.data }
        when(io.walk.response.fire) {
            when(io.walk.response.bits.error) { fail(false.B) }.otherwise {
                if (!p.fpgaTimingCuts) { pte := io.walk.response.bits.data }
                nextState := walkCheck
            }
        }
        val leaf = pte(1) || pte(3)
        val illegal = !pte(0) || (!pte(1) && pte(2)) || pte(63, 54).orR
        val misaligned = (level === 2.U && pte(27, 10).orR) || (level === 1.U && pte(18, 10).orR)
        localWalkEntry := (in(lookup) && translated && canonical && !tlbHit) ||
            (in(walkCheck) && !illegal && !leaf && level =/= 0.U && !pte(4) && !pte(6) && !pte(7))
        when(in(walkCheck)) {
            when(illegal) { fail(true.B) }
                .elsewhen(leaf) {
                    when(misaligned || !permitted(pte(7, 0))) { fail(true.B) }.otherwise {
                        if (!p.fpgaTimingCuts) { pa := physical(pte(53, 10), level) }
                        nextState := authorize
                        val ppnFits = if (p.physicalBits < 56) !pte(53, p.physicalBits - 2).orR else true.B
                        when(!stale && !io.invalidate && ppnFits) {
                            val insert = Mux(level === 0.U, smallIndex(vpn), 0.U)
                            tags(insert) := vpn; ppns(insert) := pte(p.physicalBits - 3, 10)
                            levels(insert) := level; permissions(insert) := pte(7, 0)
                            valid := valid | UIntToOH(insert, p.tlbEntries)
                            fastPage.foreach { bits =>
                                val replaced = if (indexedInstructionProof)
                                    Mux(insert === 0.U, Fill(p.tlbEntries, true.B),
                                        VecInit(instructionProofOwner.get.toSeq.map(_ === insert)).asUInt)
                                    else if (indexedDataProof)
                                        Mux(insert === 0.U, Fill(p.tlbEntries, true.B),
                                            VecInit(dataReadOwner.get.toSeq.map(_ === insert)).asUInt)
                                    else UIntToOH(insert, p.tlbEntries)
                                bits := bits & ~replaced
                            }
                            fastWritePage.foreach { bits =>
                                val replaced = if (indexedDataProof)
                                    Mux(insert === 0.U, Fill(p.tlbEntries, true.B),
                                        VecInit(dataWriteOwner.get.toSeq.map(_ === insert)).asUInt)
                                    else UIntToOH(insert, p.tlbEntries)
                                bits := bits & ~replaced
                            }
                        }
                    }
                }.otherwise {
                    // U/A/D are reserved in a non-leaf PTE; G/RSW are allowed.
                    when(level === 0.U || pte(4) || pte(6) || pte(7)) { fail(true.B) }.otherwise {
                        if (!p.fpgaTimingCuts) {
                            table := pte(53, 10) << 12
                            level := level - 1.U
                        }
                        nextState := walkAuthorize
                    }
                }
        }
        when(io.invalidate) { valid := 0.U }
    }
    if (fastEnabled) {
        // IF keeps its existing direct hit protocol. D captures its one owner
        // at this boundary: never join CPU admission/translation/atomic/cache
        // admission in one combinational READY/address chain.
        // Full-page PMP proofs do not replace dynamic PTE/privilege/SUM/MXR/A/D checks.
        // Data replies stay registered: never drive store success from raw memory response.
        // Cached PMP permission covers the entire 4KiB page and is invalidated on every PMP change.
        if (instruction) {
            // With a synchronous I-cache hit, an old reply and next fetch overlap.
            when(in(receive)) {
                io.response.valid := io.physical.response.valid; io.response.bits := io.physical.response.bits
                io.response.bits.fetchSpan := span.getOrElse(false.B)
                io.physical.response.ready := io.response.ready
                when(io.physical.response.fire) { nextState := idle }
            }
            // The registered parcel aligner never presents a new memory
            // request while accepting a word reply. Its next request starts
            // after this owner has already retired. Exclude that impossible
            // same-edge turnover from READY, cutting cache tag/return -> PC
            // admission without changing any actual request edge or slot.
            val slot = in(idle) || (!registeredInstructionReturn.B &&
                in(receive) && io.physical.response.valid && io.response.ready)
            if (registeredInstructionReturn) when(!reset.asBool) {
                assert(!(io.request.valid && io.response.ready),
                    "registered parcel requester overlapped a new offer with word return readiness")
            }
            // Payload is computed from the offered virtual address BEFORE the
            // old physical response arrives. Only VALID/admission depends on
            // slot turnover. Otherwise reply -> slot -> PA mux -> tag RAM ->
            // cache classification closes a long cross-module control cone.
            // send/fastHold retain their registered, sticky owner payload.
            // Translate the offered address independently of permission/slot
            // VALID. A failed proof cannot transfer; it must not mux the live
            // PA back to the previous owner before the downstream tag RAM.
            // Only registered send/fastHold owners select their retained PA.
            when(in(idle) || in(receive)) {
                io.physical.request.bits := io.request.bits
                io.physical.request.bits.address := fastPa
                io.physical.request.bits.noAllocate :=
                    (if (p.fpgaTimingCuts) io.request.bits.noAllocate else false.B)
            }
            when(slot && fastEligible && !io.invalidate) {
                io.hit := io.request.fire
                io.request.ready := io.physical.request.ready
                io.physical.request.valid := io.request.valid
                when(io.request.valid && !io.physical.request.ready) {
                    if (!p.fpgaTimingCuts) {
                        saved := io.request.bits; pa := fastPa
                        authorizedCacheable.foreach(_ := fastCacheable)
                    }
                    nextState := fastHold
                }
                when(io.physical.request.fire) { nextState := receive; span.foreach(_ := true.B) }
            }
            when(in(fastHold)) {
                io.hit := io.request.fire
                io.request.ready := io.physical.request.ready
                io.physical.request.valid := true.B; io.physical.request.bits := saved
                io.physical.request.bits.address := pa
                io.physical.request.bits.noAllocate := (if (p.fpgaTimingCuts) saved.noAllocate else false.B)
                when(io.physical.request.fire) { nextState := receive; span.foreach(_ := true.B) }
                when(!reset.asBool) {
                    assert(io.request.valid && io.request.bits.asUInt === saved.asUInt,
                        "fast translated offered owner was withdrawn or changed before acceptance")
                }
            }
        } else {
            // Reuse saved/context/PA/noAllocate and the existing send state.
            // Capacity remains one, with a genuine registered physical offer.
            // Only lookup/authorize are skipped; success still needs real reply.
            val scalarAligned = io.request.bits.size <= 3.U &&
                MuxLookup(io.request.bits.size, false.B)(Seq(0.U -> true.B, 1.U -> !io.request.bits.address(0),
                    2.U -> !io.request.bits.address(1, 0).orR, 3.U -> !io.request.bits.address(2, 0).orR))
            val directScalar = scalarAligned && !io.request.bits.atomic
            if (p.directFastDataIssue) {
                // Full-page permission is already proven; aligned non-atomic
                // requests may hand off at the SAME acceptance edge. READY
                // stays occupancy-only. A stalled physical offer captures the
                // exact same saved/context/PA/noAllocate into ordinary send.
                // There is still one owner, never a posted response.
                // The next scalar payload is prepared independently of the
                // current reply's VALID/READY/error. Only ownership/VALID may
                // depend on requestSlot. Otherwise D-cache hit -> readHandoff
                // -> PA select -> cache classification forms a 21-level loop.
                // Registered send/fastHold keep their sticky saved payload.
                when(in(idle) || in(reply) || in(receive)) {
                    io.physical.request.bits := io.request.bits
                    io.physical.request.bits.address := fastPa
                    io.physical.request.bits.noAllocate := fastNoAllocate
                }
                when(requestSlot) {
                    io.physical.request.valid := io.request.valid && fastEligible &&
                        !io.invalidate && directScalar
                }
                when(io.physical.request.fire && requestSlot && !reset.asBool) {
                    directAccepted := true.B
                    assert(io.request.fire && fastEligible && directScalar && !io.invalidate,
                        "direct physical handoff has no real authorized scalar owner")
                }
            }
            when(requestSlot && fastEligible && !io.invalidate && io.request.fire) {
                io.hit := true.B
                if (!p.fpgaTimingCuts) { pa := fastPa }
                noAllocate := fastNoAllocate
                nextState := send
            }
        }
    }
    if (p.fpgaTimingCuts) {
        // Local next-phase equations reuse the SAME controller registers.
        // Original nextState remains the independent semantic comparison;
        // assertions do not become physical FPGA logic.
        val phases = (0 until 13).map {
            // These states cannot be entered by another walk's READY.
            // Avoid clearing every phase through the global last-wins mux.
            case 3 => localWalkEntry
            case 4 if p.withSv39 => localWalkNext.get(0)
            case 5 if p.withSv39 => localWalkNext.get(1)
            case 6 if p.withSv39 => localWalkNext.get(2)
            case 7 => (in(send) && !io.physical.request.ready) ||
                (authorizationReady && pmp.io.allow && atomicReadAllowed) ||
                ((!instruction && fastEnabled).B && requestSlot && fastEligible &&
                    !io.invalidate && io.request.fire)
            case 11 => phaseIs(stateStorage, authorize)
            case 12 => phaseIs(stateStorage, walkAuthorize)
            case bit => nextState(bit)
        }
        val locallyQualified = VecInit(phases).asUInt
        stateStorage := locallyQualified
        when(!reset.asBool) {
            assert(locallyQualified === nextState,
                "local PTW/authorization phase equations changed translation handoff")
        }
    }
    when(!reset.asBool) {
        if (!instruction && fastEnabled) when(io.request.valid && fastEligible) {
            assert(fastCacheable === I1AddressWindow.contains(fastPa, p.cacheableBase, p.cacheableBytes),
                "parallel data proof window changed exact physical cacheability")
        }
        io.readAhead.foreach { ahead =>
            when(ahead && io.request.fire) {
                assert(readHandoff,
                    "read handoff escaped successful physical completion and live cacheable proof")
            }
        }
        assert(!io.physical.response.valid || in(receive), "unowned translated memory response")
        assert(!io.walk.response.valid || in(walkReceive), "unowned PTE response")
    }
}
