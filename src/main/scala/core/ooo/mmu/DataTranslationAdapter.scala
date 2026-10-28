package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.bus.TwoEntryRegisterQueue

private[ooo] class VirtualDataRequest(p: OooParams) extends Bundle {
    val request = new DataRequest(p.dataReturnHandleBits)
    val postedProof = p.postedProofConfig.map(c => Valid(new PostedStoreProof(c)))
    val canonicalStoreOrigin = if (p.canonicalVirtualStoreOverlap) Some(Valid(new CanonicalStoreOrigin(p))) else None
    val frozenStoreProof = if (p.frozenStoreProofEnabled) Some(Valid(new FrozenStoreProof)) else None
    val context = new VmCsrState
}

private[ooo] class TranslationResponseOwner extends Bundle {
    val fault = Bool()
    val pageFault = Bool()
    val precheckedLoad = Bool()
}

private[ooo] class CheckedDataRequest(p: OooParams, classifyNextLine: Boolean = false) extends Bundle {
    val nextLineDecision = if (classifyNextLine) Some(new PmpDecisionSummary(p.pmpEntries)) else None
    val request = new DataRequest(p.dataReturnHandleBits)
    val postedProof = p.postedProofConfig.map(c => Valid(new PostedStoreProof(c)))
    val fault = Bool()
    val pageFault = Bool()
}

/** In-order DTLB boundary. Hits may enter the translated-request FIFO in the request cycle; a miss blocks new
  * translations, but already translated physical requests and responses continue. The physical port may have multiple
  * requests outstanding. Fault placeholders share its response-order queue without issuing a physical request.
  */
class DataTranslationAdapter(p: OooParams, entries: Int = 8, registerCheckedRequests: Boolean = false,
    translationHitFlow: Boolean = false, usePublishedPmpChanges: Boolean = false,
    val queuedHeadSelection: Boolean = false, val alignedNextLinePmp: Boolean = false,
    val registerNextLineDecision: Boolean = false, val certifiedLoadIngress: Boolean = false) extends Module {
    // One configuration source; these read-only views keep elaboration audits explicit.
    val registerCanonicalStoreEvent: Boolean = p.registeredCanonicalStoreEvent
    val factorCheckedNextAllowed: Boolean = p.factorCheckedNextAllowed

    require(!p.loadPayloadNomination || (p.coexistingPhysicalLoadIngress && certifiedLoadIngress),
        "load payload nomination requires the unchanged coexisting ordinary/certified ingress contract")
    require(!p.coexistingPhysicalLoadIngress || (certifiedLoadIngress && p.bankedRobCompletionData &&
        p.identityDataRequestFlow && p.bufferedRamStores && p.registeredMemoryRequests &&
        p.registeredTranslationHeads && registerCheckedRequests && !p.physicalLoadIngressFlow),
        "coexisting ordinary ingress requires the exact registered integer/FP production contract")
    require(!certifiedLoadIngress || (p.guardedNaturalDataPmp && p.combinedCheckedDataFlow &&
        p.precheckedDataRequestFlow && p.registeredTranslationHeads && registerCheckedRequests &&
        p.registeredMemoryRequests && !p.physicalLoadIngressFlow && !p.registeredDataTranslation),
        "certified ingress requires the guarded combined profile and retains the non-flow checked boundary")
    require(!p.guardedNaturalDataPmp || (registerCheckedRequests && p.registeredTranslationHeads &&
        translationHitFlow && p.combinedCheckedDataFlow && !p.registeredDataTranslation &&
        !p.factoredDataPmpRange && !queuedHeadSelection && !registerCanonicalStoreEvent),
        "guarded natural data PMP requires the old elastic checked boundary and demand-hit route")
    require(!p.registeredDataTranslation || (registerCheckedRequests && !translationHitFlow && !queuedHeadSelection),
        "M2 requires a real registered result boundary, not a simultaneous hit/late-head shortcut")
    require(!p.registeredRawCertifiedFlow || (p.registeredDataTranslation && p.precheckedDataRequestFlow &&
        !p.combinedCheckedDataFlow && !translationHitFlow && registerCheckedRequests &&
        p.registeredTranslationHeads && !queuedHeadSelection && !registerCanonicalStoreEvent),
        "registered raw/certified flow requires its separate registered ingress/result authorization policy")
    require(!registerNextLineDecision || (registerCheckedRequests && p.dataNextLinePrefetch && alignedNextLinePmp),
        "next-line classification requires the existing checked register and aligned line permission")
    require(!p.frozenStoreCheckedFlow || registerCheckedRequests,
        "frozen checked flow retains the non-flow checked authorization register")
    require(!factorCheckedNextAllowed || (registerCheckedRequests && p.dataNextLinePrefetch),
        "checked hint factoring requires the non-flow checked queue and enabled next-line prefetch")
    require(!usePublishedPmpChanges || p.pmpChangePublicationEnabled,
        "published PMP changes require the integrated same-clock CSR producer contract")
    require(!translationHitFlow || (registerCheckedRequests && p.registeredTranslationHeads &&
        p.virtualRamLoadPrecheck && (!p.precheckedDataRequestFlow || p.combinedCheckedDataFlow)),
        "translation hit flow requires registered permission and explicit combined-mode authorization")
    require(p.virtualMemoryLevels > 0 && Set(4, 8, 16).contains(entries))
    require(!p.postedStoreMerge || registerCheckedRequests,
        "posted proof needs the common registered checked boundary before every MMIO router")
    require(!p.virtualRamLoadPrecheck || registerCheckedRequests,
        "virtual load precheck requires a registered physical authorization boundary")
    require(!p.canonicalVirtualStoreOverlap || (p.virtualRamLoadPrecheck &&
        p.registeredTranslationHeads && registerCheckedRequests),
        "canonical store certificates require the shared epoch and registered translation/checked boundaries")
    require(!p.frozenStoreProofEnabled || (p.canonicalVirtualStoreOverlap &&
        p.registeredTranslationHeads && registerCheckedRequests),
        "frozen stores require registered ingress, translated storage and checked physical write authorization")
    require(!p.registeredTranslationHeads || registerCheckedRequests,
        "registered translation heads require checked request capture")
    require(!p.identityDataRequestFlow || (p.registeredTranslationHeads && registerCheckedRequests),
        "identity flow preserves registered ingress and checked request boundaries")
    require(!p.precheckedDataRequestFlow || (p.virtualRamLoadPrecheck &&
        p.registeredTranslationHeads && registerCheckedRequests),
        "prechecked flow preserves certified ingress and registered physical authorization")
    require(!p.physicalLoadIngressFlow || (p.identityDataRequestFlow &&
        p.registeredTranslationHeads && registerCheckedRequests && p.registeredMemoryRequests),
        "physical ingress flow preserves the registered LSU and checked permission boundaries")
    val io = IO(new Bundle {
        val virtual = Flipped(new DataPort(p.dataReturnHandleBits))
        val physical = new DataPort(p.dataReturnHandleBits)
        val posted = p.postedProofConfig.map(c => new PostedStoreTranslationPort(c))
        val translation = new SvTranslationPort
        val loadPrecheck = if (p.virtualRamLoadPrecheck) Some(Flipped(new VirtualLoadPrecheckPort)) else None
        val translationPeek = if (p.virtualRamLoadPrecheck) Some(new SvTranslationPeekPort) else None
        val precheckFlush = if (p.virtualRamLoadPrecheck) Some(Input(Bool())) else None
        val canonicalStoreOrigin = if (p.canonicalVirtualStoreOverlap)
            Some(Input(Valid(new CanonicalStoreOrigin(p)))) else None
        val frozenStoreProof = if (p.frozenStoreProofEnabled) Some(Input(Valid(new FrozenStoreProof))) else None
        val canonicalStoreCertificate = if (p.canonicalVirtualStoreOverlap)
            Some(Output(Valid(new CanonicalStoreCertificate(p)))) else None
        val vmState = Input(new VmCsrState)
        val pmpState = Input(new PmpState)
        val pmpRawChanged = if (usePublishedPmpChanges) Some(Input(Bool())) else None
        val idle = Output(Bool())
        val physicalRequest = Output(Bool())
        val pageFault = Output(Bool())
    })

    // A registered epoch/stability boundary keeps wide CSR/PMP comparisons local, off the issue path.
    // Architectural context changes already drain accepted LSU owners and protect the CSR through retirement.
    // A hit captured during a transition cannot survive the next epoch check in preparation.
    val authorizationEpoch = if (p.virtualRamLoadPrecheck) Some(RegInit(0.U(32.W))) else None
    val authorizationChanged = if (p.virtualRamLoadPrecheck || p.postedStoreMerge) {
        val previousVm = RegInit(0.U.asTypeOf(new VmCsrState))
        // Standalone fixtures and arbitrary raw-state drivers retain the exact
        // snapshot fallback. Only an explicit integrated producer contract opts in.
        val pmpChanged = if (usePublishedPmpChanges) io.pmpRawChanged.get else if (p.pmpEntries > 0) {
            // Derived region bounds are not architectural state.
            val pmpContext = Cat(io.pmpState.cfg.take(p.pmpEntries).reverse.map(_.asUInt) ++
                io.pmpState.addr.take(p.pmpEntries).reverse.map(_.asUInt))
            val previousPmp = RegInit(0.U(pmpContext.getWidth.W))
            previousPmp := pmpContext
            previousPmp =/= pmpContext
        } else false.B
        val changed = previousVm.asUInt =/= io.vmState.asUInt || pmpChanged
        previousVm := io.vmState
        changed
    } else false.B
    if (p.virtualRamLoadPrecheck) {
        val stable = RegNext(!authorizationChanged && !io.precheckFlush.get, false.B)
        when(authorizationChanged || io.precheckFlush.get) { authorizationEpoch.get := authorizationEpoch.get + 1.U }
        val peek = io.translationPeek.get
        val precheck = io.loadPrecheck.get
        precheck.epoch := authorizationEpoch.get
        precheck.stable := stable && !io.precheckFlush.get
        peek.request.valid := precheck.request.valid && stable && !io.precheckFlush.get &&
            io.vmState.dataPrivilege =/= 3.U && io.vmState.satp(63, 60) =/= 0.U &&
            precheck.request.bits.size <= 3.U
        peek.request.bits.virtualAddress := precheck.request.bits.address
        peek.request.bits.rootPpn := io.vmState.satp(43, 0)
        peek.request.bits.asid := io.vmState.satp(59, 44)
        peek.request.bits.mode := io.vmState.satp(63, 60)
        peek.request.bits.privilege := io.vmState.dataPrivilege
        peek.request.bits.access := Mux(precheck.request.bits.write, PmpAccess.write, PmpAccess.read)
        peek.request.bits.sum := io.vmState.sum
        peek.request.bits.mxr := io.vmState.mxr
        precheck.response.valid := peek.request.valid && peek.response.valid &&
            !peek.response.bits.pageFault && !peek.response.bits.accessFault
        precheck.response.bits.physicalAddress := peek.response.bits.physicalAddress
        precheck.response.bits.pbmt := peek.response.bits.pbmt
        precheck.response.bits.epoch := authorizationEpoch.get
    }
    // Recovery/precheck invalidation is deliberately excluded: accepted committed
    // stores retain the old epoch while recovery seals and drains their owners.
    val postedEpoch = if (p.postedStoreMerge) Some(RegInit(0.U(32.W))) else None
    io.posted.foreach { posted =>
        posted.contextEpoch := postedEpoch.get
        posted.contextChanging := authorizationChanged
        when(authorizationChanged) {
            assert(posted.aggregateDrained && io.idle,
                "VM/PMP context changes require aggregate committed-store and adapter drain")
            when(posted.aggregateDrained && io.idle) { postedEpoch.get := postedEpoch.get + 1.U }
        }
        PostedStoreCpu.held(io.virtual.request, posted.upstreamProof)
    }
    def staleAuthorization(request: DataRequest): Bool = if (p.virtualRamLoadPrecheck)
        request.precheckedLoad && (request.translationEpoch =/= authorizationEpoch.get ||
            authorizationChanged || io.precheckFlush.get)
    else request.precheckedLoad
    if (p.canonicalVirtualStoreOverlap) {
        val origin = io.canonicalStoreOrigin.get
        CanonicalVirtualStore.held(io.virtual.request, origin)
        when(io.virtual.request.valid && origin.valid) {
            io.posted.foreach(posted => assert(!posted.upstreamProof.valid,
                "a virtual store origin is never physical posted-store authority"))
        }
    }
    io.frozenStoreProof.foreach { proof =>
        CanonicalVirtualStore.heldFrozen(p, io.virtual.request, io.canonicalStoreOrigin.get, proof)
    }

    // Registered queue boundaries keep the TLB CAM/PMP/TileLink arbitration off one FPGA combinational path.
    val translated = new DataTranslationResultStorage(if (p.registeredDataTranslation)
        Module(new DataTranslationResultBuffer(p, entries)).suggestName("translated").io
    else Module(new Queue(new TranslatedDataRequest(p), entries, pipe = false, flow = false))
        .suggestName("translated").io)
    val owners = CpuReturnTransport.ownerView(new TranslationResponseOwner, entries)
    val waiting = RegInit(false.B)
    val savedRequest = Reg(new DataRequest(p.dataReturnHandleBits))
    val savedProof = p.postedProofConfig.map(c => Reg(Valid(new PostedStoreProof(c))))
    val savedCanonicalStoreOrigin = if (p.canonicalVirtualStoreOverlap)
        Some(Reg(Valid(new CanonicalStoreOrigin(p)))) else None
    val savedPrivilege = Reg(UInt(2.W))
    // Register the actual virtual ingress, not merely the translated egress.
    // Capture the architectural context at upstream acceptance; a queued request
    // must not inherit a later SATP/SUM/MXR/privilege value. PMP remains checked
    // at the existing physical authorization boundary. CPU fences drain accepted
    // memory, and idle includes this queue for all integrating clients.
    val physicalIngressPass = WireDefault(false.B)
    val certifiedIngressPass = if (certifiedLoadIngress) WireDefault(false.B) else false.B
    val virtualRequests = if (p.registeredTranslationHeads)
        Some(Module(new TwoEntryRegisterQueue(new VirtualDataRequest(p)))) else None
    virtualRequests.foreach { stage =>
        stage.io.enq.valid := (if (certifiedLoadIngress)
            io.virtual.request.valid && !physicalIngressPass && !certifiedIngressPass
        else io.virtual.request.valid && !physicalIngressPass)
        stage.io.enq.bits.request := io.virtual.request.bits
        stage.io.enq.bits.context := io.vmState
        stage.io.enq.bits.postedProof.foreach(_ := io.posted.get.upstreamProof)
        stage.io.enq.bits.canonicalStoreOrigin.foreach(_ := io.canonicalStoreOrigin.get)
        stage.io.enq.bits.frozenStoreProof.foreach(_ := io.frozenStoreProof.get)
        io.virtual.request.ready := stage.io.enq.ready
    }
    val incoming = virtualRequests.map { stage =>
        val request = Wire(Decoupled(new DataRequest(p.dataReturnHandleBits)))
        request.valid := stage.io.deq.valid
        request.bits := stage.io.deq.bits.request
        stage.io.deq.ready := request.ready
        request
    }.getOrElse(io.virtual.request)
    val incomingProof = p.postedProofConfig.map { _ =>
        virtualRequests.map(_.io.deq.bits.postedProof.get).getOrElse(io.posted.get.upstreamProof)
    }
    val incomingCanonicalStoreOrigin = if (p.canonicalVirtualStoreOverlap)
        Some(virtualRequests.get.io.deq.bits.canonicalStoreOrigin.get) else None
    val incomingFrozenStoreProof = if (p.frozenStoreProofEnabled)
        Some(virtualRequests.get.io.deq.bits.frozenStoreProof.get) else None
    val context = virtualRequests.map(_.io.deq.bits.context).getOrElse(io.vmState)
    val frozenPresent = incomingFrozenStoreProof.map(_.valid).getOrElse(false.B)
    // Full-token identity comes from the exact synchronized LSU origin; DataRequest has no
    // independent token to compare here. Validate the fields this boundary actually observes.
    // A present malformed/stale binding must fault, never fall back to a different translation.
    val active = incoming.bits.virtualized && !incoming.bits.precheckedLoad && !frozenPresent
    def frozenVirtualContext(address: UInt, context: VmCsrState): Bool = {
        val mode = context.satp(63, 60)
        val canonical = MuxLookup(mode, false.B)(Seq(
            8.U -> (address(63, 39) === Fill(25, address(38))),
            9.U -> (address(63, 48) === Fill(16, address(47))),
            10.U -> (address(63, 57) === Fill(7, address(56)))))
        context.dataPrivilege =/= 3.U && mode >= 8.U && mode <= (p.virtualMemoryLevels + 5).U && canonical
    }
    val frozenIngressAllowed = if (p.frozenStoreProofEnabled) {
        val origin = incomingCanonicalStoreOrigin.get
        origin.valid && CanonicalVirtualStore.frozenMatches(p, incoming.bits, incomingFrozenStoreProof.get.bits) &&
            frozenVirtualContext(incoming.bits.address, context) && io.loadPrecheck.get.stable &&
            !authorizationChanged && !io.precheckFlush.get && origin.bits.epoch === authorizationEpoch.get &&
            !incomingProof.map(_.valid).getOrElse(false.B)
    } else false.B
    val canAccept = !waiting && translated.io.enq.ready
    // The accepted bound write already carries its PA, but no completion authority.
    // Keep real translated credit for a spill; downstream READY never reaches ingress.
    val frozenCheckedOffer = if (p.frozenStoreCheckedFlow)
        incoming.valid && frozenPresent && frozenIngressAllowed && canAccept && !translated.io.deq.valid
    else false.B
    val frozenCheckedPass = WireDefault(false.B)
    val identityOffer = if (p.identityDataRequestFlow)
        incoming.valid && !active && !incoming.bits.precheckedLoad && !frozenPresent &&
            canAccept && !translated.io.deq.valid else false.B
    val identityPass = WireDefault(false.B)
    // A certified load already carries its PA at the registered ingress. It can
    // share the empty translated-queue shortcut, but must still use the full
    // PMP/epoch/shape/range authorization below. Older translated work wins.
    val precheckedOffer = if (p.precheckedDataRequestFlow)
        incoming.valid && incoming.bits.precheckedLoad && !frozenPresent &&
            canAccept && !translated.io.deq.valid else false.B
    val precheckedPass = WireDefault(false.B)
    // The CPU has already checked ordinary physical load permissions before its
    // registered request FIFO. With no older ingress/translated/walker owner, an
    // aligned in-aperture read may enter checked directly. No request can reach
    // the physical port without that register, and a blocked checked queue spills
    // the accepted request into virtualRequests rather than losing/reoffering it.
    // Stores, atomics, MMIO, uncached and virtual/certified accesses stay staged.
    // Coexistence is a new opt-in route, not relaxation of the old profile guard.
    // The final producer has already authorized the ordinary physical request:
    // integer LSU -> non-flow FIFO -> StoreBuffer, or FP LSU(registerStart=true).
    // Classification does not create PMP/ROB authority. No permission/fire/physical
    // READY feeds this nominal selection; both capture credits are old occupancy.
    val coexistingPhysicalIngressNominal = if (p.coexistingPhysicalLoadIngress) {
        val offered = io.virtual.request.bits
        val privilege = io.vmState.dataPrivilege
        val bareContext = (privilege === 0.U || privilege === 1.U || privilege === 3.U) &&
            (privilege === 3.U || io.vmState.satp(63, 60) === 0.U)
        val noSidecars = !io.posted.map(_.upstreamProof.valid).getOrElse(false.B) &&
            !io.canonicalStoreOrigin.map(_.valid).getOrElse(false.B) &&
            !io.frozenStoreProof.map(_.valid).getOrElse(false.B)
        io.virtual.request.valid && virtualRequests.get.io.enq.ready &&
            !virtualRequests.get.io.deq.valid && !translated.io.deq.valid && !waiting &&
            !offered.virtualized && !offered.precheckedLoad && !offered.write && !offered.atomic &&
            !offered.uncached && noSidecars && bareContext &&
            AlignedMemoryDisjoint.aligned(offered.address, offered.size) &&
            offered.mask === AlignedMemoryDisjoint.lanes(offered.address, offered.size) &&
            SpeculativeRamRange.contains(p, offered.address, offered.size) &&
            io.loadPrecheck.get.stable && !authorizationChanged && !io.precheckFlush.get
    } else false.B
    val physicalIngressOffer = if (p.coexistingPhysicalLoadIngress) coexistingPhysicalIngressNominal
    else if (p.physicalLoadIngressFlow) {
        val offered = io.virtual.request.bits
        io.virtual.request.valid && virtualRequests.get.io.enq.ready &&
            !virtualRequests.get.io.deq.valid && !translated.io.deq.valid && !waiting &&
            !offered.virtualized && !offered.precheckedLoad && !offered.write && !offered.atomic &&
            !io.frozenStoreProof.map(_.valid).getOrElse(false.B) &&
            !offered.uncached && AlignedMemoryDisjoint.aligned(offered.address, offered.size) &&
            SpeculativeRamRange.contains(p, offered.address, offered.size)
    } else false.B

    // This source is built at the FINAL adapter port, after StoreBuffer and FP
    // arbitration. The original request and every fallback sidecar stay intact.
    val certifiedIngressDescriptor = if (certifiedLoadIngress) {
        val builder = Module(new CertifiedIngressDescriptorBuilder(p))
        builder.io.request := io.virtual.request.bits
        builder.io.context := io.vmState
        builder.io.authorization.epoch := authorizationEpoch.get
        builder.io.authorization.stable := io.loadPrecheck.get.stable
        builder.io.authorization.changing := authorizationChanged
        builder.io.authorization.flush := io.precheckFlush.get
        builder.io.postedPresent := io.posted.map(_.upstreamProof.valid).getOrElse(false.B)
        builder.io.canonicalPresent := io.canonicalStoreOrigin.map(_.valid).getOrElse(false.B)
        builder.io.frozenPresent := io.frozenStoreProof.map(_.valid).getOrElse(false.B)
        Some(builder.io.descriptor)
    } else None
    // Nominal selection MUST NOT depend on permission, checked credit/fire, or
    // ingress enqueue fire. Even a denied descriptor remains selected this cycle.
    val certifiedIngressNominal = if (certifiedLoadIngress) {
        val offered = io.virtual.request.bits
        io.virtual.request.valid && virtualRequests.get.io.enq.ready &&
            !virtualRequests.get.io.deq.valid && !translated.io.deq.valid && !waiting &&
            offered.precheckedLoad && !offered.virtualized && !offered.write && !offered.atomic &&
            !offered.uncached && certifiedIngressDescriptor.get.sidecarsAbsent
    } else false.B

    // Fifth-batch payload selection only: no shape/range/context/authorization or
    // downstream credit feeds this wide-data nomination. The original complete
    // physicalIngressOffer above remains the ONLY ordinary authorization gate.
    // With older work absent, an ineligible nominal record changes invalid bits
    // only and still falls back through the original ingress queue unchanged.
    val ordinaryPayloadNominal = if (p.loadPayloadNomination) {
        val offered = io.virtual.request.bits
        io.virtual.request.valid && virtualRequests.get.io.enq.ready &&
            !virtualRequests.get.io.deq.valid && !translated.io.deq.valid && !waiting &&
            !offered.precheckedLoad && !offered.virtualized && !offered.write &&
            !offered.atomic && !offered.uncached && certifiedIngressDescriptor.get.sidecarsAbsent
    } else false.B
    val rawPayloadNominal = if (p.loadPayloadNomination)
        ordinaryPayloadNominal || certifiedIngressNominal else false.B

    io.translation.request.valid := incoming.valid && active && canAccept
    io.translation.request.bits.virtualAddress := incoming.bits.address
    io.translation.request.bits.rootPpn := context.satp(43, 0)
    io.translation.request.bits.asid := context.satp(59, 44)
    io.translation.request.bits.mode := context.satp(63, 60)
    io.translation.request.bits.privilege := context.dataPrivilege
    io.translation.request.bits.access := Mux(incoming.bits.atomic,
        Mux(incoming.bits.atomicOp === 2.U, PmpAccess.read,
            Mux(incoming.bits.atomicOp === 3.U, PmpAccess.write, PmpAccess.readWrite)),
        Mux(incoming.bits.write, PmpAccess.write, PmpAccess.read))
    io.translation.request.bits.sum := context.sum
    io.translation.request.bits.mxr := context.mxr
    incoming.ready := canAccept && Mux(active, io.translation.request.ready, true.B)
    // A TLB hit can produce a response in the request cycle. Its request.ready already
    // depends on response.ready, so this must not depend on request.fire.
    io.translation.response.ready := translated.io.enq.ready

    val translatedReply = io.translation.response.valid && (waiting || io.translation.request.fire)
    // Only a same-edge demand hit, never a delayed walk/fault, may skip the empty
    // translated FIFO. The checked register and final PMP/epoch checks remain.
    // Response READY still depends on FIFO space, not the external physical port:
    // if checked cannot take it, the already-accepted result spills into that FIFO.
    val translationHitOffer = if (translationHitFlow) active && !waiting && translatedReply &&
        !translated.io.deq.valid && !incoming.bits.atomic && !incoming.bits.uncached &&
        !io.translation.response.bits.pageFault && !io.translation.response.bits.accessFault &&
        io.translation.response.bits.pbmt === 0.U && !authorizationChanged && !io.precheckFlush.get
        else false.B
    val translationHitPass = WireDefault(false.B)
    translated.io.enq.valid := ((!waiting && incoming.valid && !active && !identityPass && !precheckedPass) ||
        translatedReply) && !translationHitPass && !frozenCheckedPass
    val original = Mux(waiting, savedRequest, incoming.bits)
    val frozenSource = !waiting && frozenPresent
    translated.io.enq.bits := 0.U.asTypeOf(new TranslatedDataRequest(p))
    translated.io.enq.bits.request := original
    translated.io.enq.bits.postedProof.foreach(_ := Mux(waiting, savedProof.get, incomingProof.get))
    translated.io.enq.bits.canonicalStoreOrigin.foreach { origin =>
        origin := Mux(waiting, savedCanonicalStoreOrigin.get, incomingCanonicalStoreOrigin.get)
        // Preserve origin only for a genuine demand-write reply or the explicitly
        // typed frozen-write source. Legacy origin alone cannot bypass translation.
        origin.valid := Mux(waiting, savedCanonicalStoreOrigin.get.valid, incomingCanonicalStoreOrigin.get.valid) &&
            (translatedReply || frozenSource) && original.virtualized && original.write && !original.atomic &&
            !original.precheckedLoad && !original.uncached
    }
    translated.io.enq.bits.frozenStorePresent.foreach(_ := frozenSource)
    translated.io.enq.bits.originalVirtualAddress.foreach(_ := original.address)
    translated.io.enq.bits.request.address := Mux(frozenSource,
        incomingFrozenStoreProof.map(_.bits.physicalAddress).getOrElse(0.U),
        Mux(active || waiting, io.translation.response.bits.physicalAddress, original.address))
    translated.io.enq.bits.request.virtualized := false.B
    translated.io.enq.bits.request.uncached := original.uncached ||
        ((active || waiting) && io.translation.response.bits.pbmt =/= 0.U)
    translated.io.enq.bits.privilege := Mux(waiting, savedPrivilege, context.dataPrivilege)
    translated.io.enq.bits.checkPhysical := active || waiting || original.precheckedLoad || frozenSource
    translated.io.enq.bits.pageFault := (active || waiting) && io.translation.response.bits.pageFault
    translated.io.enq.bits.accessFault := ((active || waiting) && io.translation.response.bits.accessFault) ||
        (frozenSource && !frozenIngressAllowed) || staleAuthorization(original) || (original.precheckedLoad &&
            (original.virtualized || original.write || original.atomic || original.uncached ||
                context.dataPrivilege === 3.U || context.satp(63, 60) === 0.U))
    if (p.frozenStoreProofEnabled) {
        when(incoming.fire && frozenPresent) {
            if (p.frozenStoreCheckedFlow) {
                assert((translated.io.enq.fire ^ frozenCheckedPass) && !io.translation.request.fire && !waiting &&
                    !identityPass && !precheckedPass && !physicalIngressPass && !translationHitPass,
                    "frozen store transfers exactly once into translated storage or checked authorization")
            } else {
                assert(translated.io.enq.fire && !io.translation.request.fire && !waiting &&
                    !identityPass && !precheckedPass && !physicalIngressPass,
                    "frozen store transfers once into translated storage without demand retranslation or flow bypass")
            }
            assert(translated.io.enq.bits.frozenStorePresent.get,
                "registered ingress retains frozen provenance")
            when(frozenIngressAllowed) {
                val proof = incomingFrozenStoreProof.get.bits
                val captured = translated.io.enq.bits
                assert(captured.originalVirtualAddress.get === proof.address &&
                    captured.request.address === proof.physicalAddress && captured.request.size === proof.size &&
                    captured.request.mask === proof.mask &&
                    captured.canonicalStoreOrigin.get.asUInt === incomingCanonicalStoreOrigin.get.asUInt,
                    "accepted compact binding retains the full incoming tuple and origin")
            }.otherwise {
                assert(translated.io.enq.bits.accessFault,
                    "rejected frozen ingress remains a fault after compact capture")
            }
        }
    }

    when(io.translation.request.fire && !io.translation.response.fire) {
        waiting := true.B
        savedRequest := incoming.bits
        savedProof.foreach(_ := incomingProof.get)
        savedCanonicalStoreOrigin.foreach(_ := incomingCanonicalStoreOrigin.get)
        savedPrivilege := context.dataPrivilege
    }
    when(waiting && io.translation.response.fire) { waiting := false.B }
    if (p.registeredDataTranslation) {
        when(io.translation.response.fire) {
            assert(translated.io.enq.fire,
                "M2 accepted translation response must enter its registered result owner exactly once")
        }
    }

    // The optional hit source ends at the same checked register as queued work.
    // It never bypasses authorization or an older translated request.
    // Do not reuse translated.enq.bits here: it contains live demand-response
    // PA/PBMT/fault mux inputs even when a mutually exclusive certified offer
    // logically selects another arm. This separate descriptor gives the new
    // mode a structural, rather than merely functional, CAM-to-PMP boundary.
    val certifiedHead = if (p.registeredRawCertifiedFlow) {
        val certified = Wire(new TranslatedDataRequest(p))
        certified := 0.U.asTypeOf(new TranslatedDataRequest(p))
        certified.request := incoming.bits
        certified.request.virtualized := false.B
        certified.privilege := context.dataPrivilege
        certified.checkPhysical := true.B
        certified.pageFault := false.B
        certified.accessFault := staleAuthorization(incoming.bits) || !incoming.bits.precheckedLoad ||
            incoming.bits.virtualized || incoming.bits.write || incoming.bits.atomic || incoming.bits.uncached ||
            context.dataPrivilege === 3.U || context.satp(63, 60) === 0.U
        certified.originalVirtualAddress.foreach(_ := incoming.bits.address)
        // The zero origin is intentional: a certified load is never store authority.
        Some(certified)
    } else None
    // New-source selection is elaborated only for the opt-in profile. Keep the
    // disabled head expression and name identical to the established boundary.
    // Keep the complete certified head for fault/PMP/context/store-lineage.
    // Only its legacy request payload is separately available to the new mux.
    val legacyPayloadHead = if (p.loadPayloadNomination) Some(Wire(new TranslatedDataRequest(p))) else None
    val head = if (certifiedLoadIngress) {
        val legacyHead = if (p.registeredRawCertifiedFlow) {
            // Selection depends only on registered FIFO occupancy. The checked
            // valid/enable uses registered ingress offer/credit, never raw reply.
            Mux(translated.io.deq.valid, translated.io.deq.bits, certifiedHead.get)
        } else if (p.precheckedDataRequestFlow || translationHitFlow || p.frozenStoreCheckedFlow) {
            // These offers require an empty translated queue. When occupied, its
            // registered valid bit selects the older record before hit/PBMT/fault
            // qualification. When empty, only an authorized offer may consume this
            // raw ingress record; identity/physical ingress use their own payloads.
            // Valid/fire and every authorization gate remain unchanged below.
            if (queuedHeadSelection) Mux(translated.io.deq.valid, translated.io.deq.bits, translated.io.enq.bits)
            else Mux(precheckedOffer || translationHitOffer || frozenCheckedOffer, translated.io.enq.bits, translated.io.deq.bits)
        } else translated.io.deq.bits
        legacyPayloadHead.foreach(_ := legacyHead)
        // Permission never feeds this nominal payload/context/fault/hint mux.
        Mux(certifiedIngressNominal, certifiedIngressDescriptor.get.result, legacyHead)
    } else if (p.registeredRawCertifiedFlow) {
        // Selection depends only on registered FIFO occupancy. The checked
        // valid/enable uses registered ingress offer/credit, never raw reply.
        Mux(translated.io.deq.valid, translated.io.deq.bits, certifiedHead.get)
    } else if (p.precheckedDataRequestFlow || translationHitFlow || p.frozenStoreCheckedFlow) {
        // These offers require an empty translated queue. When occupied, its
        // registered valid bit selects the older record before hit/PBMT/fault
        // qualification. When empty, only an authorized offer may consume this
        // raw ingress record; identity/physical ingress use their own payloads.
        // Valid/fire and every authorization gate remain unchanged below.
        if (queuedHeadSelection) Mux(translated.io.deq.valid, translated.io.deq.bits, translated.io.enq.bits)
        else Mux(precheckedOffer || translationHitOffer || frozenCheckedOffer, translated.io.enq.bits, translated.io.deq.bits)
    } else translated.io.deq.bits
    val request = head.request
    // Ordinary and certified ingress carry exactly the same final-port request
    // bundle. Their authority, fault, privilege and sidecars are NOT combined.
    // Feature OFF retains each established expression at its original use site.
    val nominatedCheckedPayload = if (p.loadPayloadNomination) Some(Mux(rawPayloadNominal,
        io.virtual.request.bits, Mux(identityOffer, incoming.bits, legacyPayloadHead.get.request))) else None
    val previousCheckedPayload = if (p.loadPayloadNomination) Some(Mux(physicalIngressOffer,
        io.virtual.request.bits, Mux(identityOffer, incoming.bits, request))) else None
    val permission = if (p.registeredDataTranslation)
        Some(Module(new DataPhysicalPermissionEvaluator(p, alignedNextLinePmp,
            factorCheckedNextAllowed, registerNextLineDecision))) else None
    permission.foreach { evaluator =>
        evaluator.io.result := head
        evaluator.io.pmpState := io.pmpState
        evaluator.io.authorization.epoch := authorizationEpoch.get
        evaluator.io.authorization.stable := io.loadPrecheck.get.stable
        evaluator.io.authorization.changing := authorizationChanged
        evaluator.io.authorization.flush := io.precheckFlush.get
        CpuReturnTransport.requestPayload(evaluator.io.hintRequest,
            Mux(physicalIngressOffer, io.virtual.request.bits, Mux(identityOffer, incoming.bits, request)))
        evaluator.io.hintPrivilege := Mux(physicalIngressOffer, io.vmState.dataPrivilege,
            Mux(identityOffer, context.dataPrivilege, head.privilege))
        evaluator.io.hintBypassFault := identityOffer || physicalIngressOffer
    }
    val legacyPmp = if (!p.registeredDataTranslation) {
        val access = Mux(request.atomic,
            Mux(request.atomicOp === 2.U, PmpAccess.read,
                Mux(request.atomicOp === 3.U, PmpAccess.write, PmpAccess.readWrite)),
            Mux(request.write, PmpAccess.write, PmpAccess.read))
        // Only the checker sees normalization. The original request remains untouched,
        // including during faults, for exact payload, owner, address and tval reporting.
        // Two-bit DataRequest.size makes the natural checker's <= 8-byte domain structural.
        val checkerAddress = if (p.guardedNaturalDataPmp) {
            val alignmentMask = MuxLookup(request.size, 7.U(3.W))(
                Seq(0.U -> 0.U, 1.U -> 1.U, 2.U -> 3.U))
            Cat(request.address(63, 3), request.address(2, 0) & ~alignmentMask)
        } else request.address
        val denied = if (p.decodedNaturalPmp) {
            NaturalPmpEvaluation.denied(p.pmpEntries, true, false, io.pmpState,
                checkerAddress, request.size, head.privilege, access)
        } else {
            val pmp = Module(new PmpChecker(p.pmpEntries, factoredGenericRanges = p.factoredDataPmpRange,
                naturalAlignedAccess = p.guardedNaturalDataPmp))
            pmp.io.state := io.pmpState
            pmp.io.address := checkerAddress
            pmp.io.size := request.size
            pmp.io.privilege := head.privilege
            pmp.io.access := access
            pmp.io.denied
        }
        Some((denied, access))
    } else None
    val pmpDenied = permission.map(_.io.pmpDenied).getOrElse(legacyPmp.get._1)
    val pmpAccess = permission.map(_.io.access).getOrElse(legacyPmp.get._2)
    val atomicOutside = request.atomic && head.checkPhysical &&
        !SpeculativeRamRange.contains(p, request.address, request.size)
    val precheckedShapeFault = if (p.precheckedDataRequestFlow) {
        val mask = MuxLookup(request.size, 255.U(8.W))(Seq(0.U -> 1.U, 1.U -> 3.U, 2.U -> 15.U))
        request.precheckedLoad && (!AlignedMemoryDisjoint.aligned(request.address, request.size) ||
            request.mask =/= (mask << request.address(2, 0))(7, 0))
    } else false.B
    val frozenCheckedAllowed = if (p.frozenStoreProofEnabled) {
        // For allowed ingress this tuple equals the full original proof. A rejected binding
        // cannot regain authority through reconstruction: its accessFault remains sticky.
        val proof = Wire(new FrozenStoreProof)
        proof.address := head.originalVirtualAddress.get
        proof.physicalAddress := request.address
        proof.size := request.size
        proof.mask := request.mask
        val origin = head.canonicalStoreOrigin.get
        origin.valid && request.write && !request.atomic && !request.virtualized &&
            !request.precheckedLoad && !request.uncached && head.checkPhysical &&
            CanonicalVirtualStore.frozenShape(p, proof) &&
            frozenVirtualContext(proof.address, io.vmState) && io.loadPrecheck.get.stable &&
            !authorizationChanged && !io.precheckFlush.get && origin.bits.epoch === authorizationEpoch.get &&
            !head.postedProof.map(_.valid).getOrElse(false.B)
    } else false.B
    val frozenFault = head.frozenStorePresent.map(present => present && !frozenCheckedAllowed).getOrElse(false.B)
    val fault = permission.map(_.io.fault).getOrElse(
        head.pageFault || head.accessFault || precheckedShapeFault || frozenFault ||
            (head.checkPhysical && pmpDenied) || atomicOutside || staleAuthorization(request) ||
            (request.precheckedLoad && !SpeculativeRamRange.contains(p, request.address, request.size)))
    // Snapshot the request and fault decision before downstream grants.
    // Fault placeholders remain ordered but never issue physical requests.
    // Both checked implementations are non-flow: hint permission and fault always
    // cross the same register edge before optional reconstruction at dequeue.
    // This guard is driven from the actual selected original checked payload below,
    // not from a normalized PMP address or an unrelated empty translated head.
    val guardedCheckedAlignmentFault = if (p.guardedNaturalDataPmp) Some(Wire(Bool())) else None
    val certifiedIngressOffer = if (certifiedLoadIngress)
        certifiedIngressNominal && certifiedIngressDescriptor.get.routeQualified &&
            !fault && !guardedCheckedAlignmentFault.get
    else false.B
    val checked: Option[QueueIO[CheckedDataRequest]] = if (registerCheckedRequests)
        Some(if (p.registeredTranslationHeads)
            Module(new TwoEntryRegisterQueue(new CheckedDataRequest(p, registerNextLineDecision))).suggestName("checked").io
        else Module(new Queue(new CheckedDataRequest(p, registerNextLineDecision), 2, pipe = false, flow = false)).suggestName("checked").io)
    else None
    checked.foreach { stage =>
        if (p.identityDataRequestFlow || p.precheckedDataRequestFlow || p.physicalLoadIngressFlow ||
            translationHitFlow || p.frozenStoreCheckedFlow || certifiedLoadIngress) {
            // Empty-FIFO pass-through retains the same final checked authorization.
            // If checked stalls, the identical offer spills into translated,
            // preserving held payload and capacity without a ready path from
            // the external physical port. Older translated work always wins.
            stage.enq.valid := translated.io.deq.valid || identityOffer || precheckedOffer || physicalIngressOffer ||
                translationHitOffer || frozenCheckedOffer || certifiedIngressOffer
            stage.enq.bits.request := (if (p.loadPayloadNomination) nominatedCheckedPayload.get
                else Mux(physicalIngressOffer, io.virtual.request.bits, Mux(identityOffer, incoming.bits, request)))
            stage.enq.bits.fault := Mux(identityOffer || physicalIngressOffer, false.B, fault)
            stage.enq.bits.pageFault := Mux(identityOffer || physicalIngressOffer, false.B, head.pageFault)
            identityPass := identityOffer && stage.enq.ready
            precheckedPass := precheckedOffer && stage.enq.ready
            physicalIngressPass := physicalIngressOffer && stage.enq.ready
            if (certifiedLoadIngress) certifiedIngressPass := certifiedIngressOffer && stage.enq.ready
            translationHitPass := translationHitOffer && stage.enq.ready
            frozenCheckedPass := frozenCheckedOffer && stage.enq.ready
            when(frozenCheckedPass) {
                assert(incoming.fire && stage.enq.fire && !translated.io.enq.fire &&
                    !translated.io.deq.valid && !waiting && frozenPresent && frozenIngressAllowed && !active &&
                    !io.translation.request.fire && !identityPass && !precheckedPass &&
                    !physicalIngressPass && !translationHitPass &&
                    head.asUInt === translated.io.enq.bits.asUInt,
                    "bound frozen store transfers once through the original checked authorization boundary")
            }
            when(frozenCheckedOffer && !stage.enq.ready) {
                assert(incoming.fire && translated.io.enq.fire && !frozenCheckedPass,
                    "blocked frozen checked offer spills once using existing translated credit")
            }
            when(translationHitPass) {
                assert(incoming.fire && io.translation.request.fire && io.translation.response.fire &&
                    stage.enq.fire && !translated.io.enq.fire && !translated.io.deq.valid &&
                    !waiting && active && !identityPass && !precheckedPass && !physicalIngressPass,
                    "demand TLB hit must transfer exactly once through checked authorization")
            }
            when(identityPass) {
                assert(incoming.fire && !translated.io.enq.fire && !waiting && !active,
                    "identity request must transfer exactly once after authorization")
            }
            when(precheckedPass) {
                assert(incoming.fire && !translated.io.enq.fire && !waiting && !active &&
                    !translated.io.deq.valid && !identityPass,
                    "certified request transfers once through registered physical authorization")
            }
            when(physicalIngressPass) {
                assert(io.virtual.request.fire && !virtualRequests.get.io.enq.fire &&
                    !incoming.fire && !translated.io.enq.fire && !translated.io.deq.valid &&
                    !waiting && !identityPass && !precheckedPass,
                    "physical ingress shortcut transfers one load through the checked register")
            }
        } else {
            stage.enq.valid := translated.io.deq.valid
            stage.enq.bits.request := request
            stage.enq.bits.fault := fault
            stage.enq.bits.pageFault := head.pageFault
        }
        if (p.guardedNaturalDataPmp) {
            val malformed = !AlignedMemoryDisjoint.aligned(stage.enq.bits.request.address, stage.enq.bits.request.size)
            guardedCheckedAlignmentFault.get := malformed
            // Place the guard AFTER identity/physical-ingress bypass selection. Those
            // shortcuts cannot clear a malformed standalone request's access error.
            stage.enq.bits.fault := Mux(identityOffer || physicalIngressOffer, false.B, fault) || malformed
        }
        translated.io.deq.ready := stage.enq.ready
    }
    if (p.loadPayloadNomination) {
        val stage = checked.get
        when(rawPayloadNominal) {
            assert(!incoming.valid && !translated.io.deq.valid && !waiting &&
                !identityOffer && !precheckedOffer && !translationHitOffer && !frozenCheckedOffer,
                "raw payload nomination cannot displace older registered or translated work")
            assert(!(ordinaryPayloadNominal && certifiedIngressNominal),
                "ordinary and certified payload nominations are disjoint request types")
        }
        when(ordinaryPayloadNominal && stage.enq.valid) {
            assert(physicalIngressOffer,
                "ordinary nomination never creates checked validity without the original full offer")
        }
        when(physicalIngressOffer) {
            assert(ordinaryPayloadNominal, "every authorized ordinary offer retains its final-port payload")
        }
        when(certifiedIngressNominal) {
            assert(certifiedIngressDescriptor.get.result.request.asUInt === io.virtual.request.bits.asUInt,
                "common raw payload selection never rewrites certified request metadata")
        }
        when(stage.enq.valid) {
            // Includes every request field, even input hint, before the common
            // overwrite below; next-line privilege/fault/PMP inputs stay original.
            assert(nominatedCheckedPayload.get.asUInt === previousCheckedPayload.get.asUInt,
                "every valid checked payload equals the fourth-batch selection bit for bit")
            assert(guardedCheckedAlignmentFault.get ===
                !AlignedMemoryDisjoint.aligned(previousCheckedPayload.get.address, previousCheckedPayload.get.size),
                "payload nomination preserves the checked alignment fault")
        }
    }
    // Authorization is captured with the checked request, including the identity
    // queue bypass. The incoming hint is always overwritten, even when disabled.
    // Factoring stores permission before the current-request fault in the existing
    // hint bit; that same record already carries the fault used at dequeue.
    private var constructedNextLineAuthorization: Option[NextLineAuthorization] = None
    def nextLineAuthorizationInstance: Option[NextLineAuthorization] = constructedNextLineAuthorization
    val nextAllowed = if (permission.nonEmpty) {
        val evaluator = permission.get
        constructedNextLineAuthorization = evaluator.nextLineAuthorization
        if (registerNextLineDecision) checked.get.enq.bits.nextLineDecision.get := evaluator.io.nextDecision.get
        evaluator.io.nextAllowed
    } else if (p.dataNextLinePrefetch) {
        val authorize = Module(new NextLineAuthorization(p, alignedLinePmp = alignedNextLinePmp,
            exportDecision = registerNextLineDecision))
        constructedNextLineAuthorization = Some(authorize)
        CpuReturnTransport.requestPayload(authorize.io.request, (if (p.loadPayloadNomination)
            nominatedCheckedPayload.get else Mux(physicalIngressOffer, io.virtual.request.bits,
                Mux(identityOffer, incoming.bits, request))))
        authorize.io.privilege := Mux(physicalIngressOffer, io.vmState.dataPrivilege,
            Mux(identityOffer, context.dataPrivilege, head.privilege))
        authorize.io.pmpState := io.pmpState
        if (p.guardedNaturalDataPmp) {
            authorize.io.fault := (if (factorCheckedNextAllowed) false.B
                else Mux(identityOffer || physicalIngressOffer, false.B, fault)) || guardedCheckedAlignmentFault.get
        } else authorize.io.fault := (if (factorCheckedNextAllowed) false.B
            else Mux(identityOffer || physicalIngressOffer, false.B, fault))
        if (registerNextLineDecision) {
            checked.get.enq.bits.nextLineDecision.get := authorize.decision.get
            authorize.eligible.get
        } else authorize.io.allowed
    } else false.B
    checked.foreach { stage =>
        stage.enq.bits.request.prefetchNextAllowed := (if (p.guardedNaturalDataPmp)
            nextAllowed && !guardedCheckedAlignmentFault.get else nextAllowed)
    }
    p.postedProofConfig.foreach { _ =>
        val stage = checked.get
        val selected = Mux(physicalIngressOffer, io.posted.get.upstreamProof,
            Mux(identityOffer, incomingProof.get, head.postedProof.get))
        val finalPmp = Module(new PmpChecker(p.pmpEntries))
        finalPmp.io.state := io.pmpState
        finalPmp.io.address := stage.enq.bits.request.address
        finalPmp.io.size := stage.enq.bits.request.size
        finalPmp.io.privilege := Mux(physicalIngressOffer, io.vmState.dataPrivilege,
            Mux(identityOffer, context.dataPrivilege, head.privilege))
        finalPmp.io.access := PmpAccess.write
        stage.enq.bits.postedProof.get := selected
        stage.enq.bits.postedProof.get.bits.finalChecked := true.B
        when(stage.enq.fire && selected.valid) {
            assert(PostedStoreCpu.matches(selected.bits, stage.enq.bits.request) &&
                selected.bits.headAuthorized && selected.bits.physicalPmpAllowed &&
                selected.bits.originalPhysical && selected.bits.integerOrigin &&
                selected.bits.legacyPostedAccepted && !selected.bits.finalChecked &&
                selected.bits.epoch === postedEpoch.get && !authorizationChanged &&
                !stage.enq.bits.fault && !finalPmp.io.denied &&
                SpeculativeRamRange.contains(p, stage.enq.bits.request.address, stage.enq.bits.request.size),
                "checked stage validates captured head/PMP/payload lineage; identity success creates no authority")
        }
    }
    if (p.canonicalVirtualStoreOverlap) {
        val stage = checked.get
        val origin = head.canonicalStoreOrigin.get
        val virtualAddress = head.originalVirtualAddress.get
        val certificate = Wire(Valid(new CanonicalStoreCertificate(p)))
        val fromTranslated = if (certifiedLoadIngress)
            (translated.io.deq.valid || translationHitOffer || frozenCheckedPass) &&
                !identityOffer && !precheckedOffer && !physicalIngressOffer && !certifiedIngressNominal
        else (translated.io.deq.valid || translationHitOffer || frozenCheckedPass) &&
            !identityOffer && !precheckedOffer && !physicalIngressOffer
        val qualified = permission.map(_.io.canonical.valid).getOrElse {
            val ordinaryStore = request.write && !request.atomic && !request.virtualized &&
                !request.precheckedLoad && !request.uncached && head.checkPhysical
            val shape = request.size <= 3.U && AlignedMemoryDisjoint.aligned(virtualAddress, request.size) &&
                AlignedMemoryDisjoint.aligned(request.address, request.size) &&
                virtualAddress(11, 0) === request.address(11, 0) &&
                request.mask === AlignedMemoryDisjoint.lanes(request.address, request.size)
            // Check the entire half-open interval at XLEN+1. Never truncate high PA
            // bits, certify only a starting byte, or wrap an access at the RAM end.
            val physicalStart = Cat(0.U(1.W), request.address)
            val bytes = MuxLookup(request.size, 8.U(65.W))(
                Seq(0.U -> 1.U(65.W), 1.U -> 2.U(65.W), 2.U -> 4.U(65.W)))
            val physicalEnd = physicalStart + bytes
            val inRam = physicalStart >= p.speculativeRamBase.U(65.W) &&
                physicalEnd <= (p.speculativeRamBase + p.speculativeRamBytes).U(65.W) &&
                physicalEnd > physicalStart
            val fresh = io.loadPrecheck.get.stable && !authorizationChanged && !io.precheckFlush.get &&
                origin.bits.epoch === authorizationEpoch.get
            origin.valid && ordinaryStore && shape && inRam && fresh && !pmpDenied
        }
        // Qualification never creates an event without the exact accepted owner.
        certificate.valid := stage.enq.fire && fromTranslated && qualified && !stage.enq.bits.fault
        permission match {
            case Some(evaluator) => certificate.bits := evaluator.io.canonical.bits
            case None =>
                certificate.bits.origin := origin.bits
                certificate.bits.virtualAddress := virtualAddress
                certificate.bits.physicalAddress := request.address
                certificate.bits.size := request.size
                certificate.bits.mask := request.mask
        }
        if (registerCanonicalStoreEvent) {
            val certificateValid = RegNext(certificate.valid, false.B)
            val certificateBits = RegEnable(certificate.bits, certificate.valid)
            io.canonicalStoreCertificate.get.valid := certificateValid
            io.canonicalStoreCertificate.get.bits := certificateBits
        } else {
            io.canonicalStoreCertificate.get := certificate
        }
        // Assertions below describe raw checked acceptance in both modes.
        val expectedCheckedRequest = WireDefault(request)
        expectedCheckedRequest.prefetchNextAllowed := nextAllowed
        when(certificate.valid) {
            assert((translated.io.deq.fire || translationHitPass || frozenCheckedPass) &&
                stage.enq.bits.request.asUInt === expectedCheckedRequest.asUInt,
                "canonical store certificate belongs to the exact checked request acceptance")
            assert(!head.pageFault && !head.accessFault && !stage.enq.bits.pageFault &&
                pmpAccess === PmpAccess.write,
                "canonical store certificate requires checked demand or frozen translation and physical write permission")
            head.postedProof.foreach(proof => assert(!proof.valid,
                "canonical virtual-store certificate cannot reuse physical posted-store proof"))
        }
        head.frozenStorePresent.foreach { present =>
            when(stage.enq.fire && fromTranslated && present && !stage.enq.bits.fault) {
                assert(frozenCheckedAllowed && certificate.valid && !pmpDenied &&
                    pmpAccess === PmpAccess.write,
                    "successful frozen stores retain fresh origin and final checked physical write authority")
            }
        }
    }
    val physicalHead = checked.map(_.deq.bits.request).getOrElse(request)
    // This final gate is narrow. The full CSR/PMP snapshot comparator terminates in checked above.
    // Context changes with accepted prechecked owners violate the drain contract asserted below.
    val physicalStale = if (p.virtualRamLoadPrecheck) physicalHead.precheckedLoad &&
        (physicalHead.translationEpoch =/= authorizationEpoch.get || io.precheckFlush.get)
    else physicalHead.precheckedLoad
    val physicalFault = checked.map(_.deq.bits.fault).getOrElse(fault) || physicalStale
    val physicalPageFault = checked.map(_.deq.bits.pageFault).getOrElse(head.pageFault)
    val physicalValid = checked.map(_.deq.valid).getOrElse(translated.io.deq.valid)
    // This is the common checked -> APLIC/external-memory boundary. Only older
    // cache responsibility blocks a nonposted head. Neither this head nor younger
    // ingress/FIFO/SB work participates in its own older-drain predicate.
    val orderedAllowed = io.posted.map(posted =>
        checked.get.deq.bits.postedProof.get.valid || !posted.externalBusy).getOrElse(true.B)
    val physicalReady = orderedAllowed && owners.io.enq.ready && (physicalFault || io.physical.request.ready)
    checked match {
        case Some(stage) => stage.deq.ready := physicalReady
        case None => translated.io.deq.ready := physicalReady
    }
    io.physical.request.valid := physicalValid && !physicalFault && owners.io.enq.ready && orderedAllowed
    io.physical.request.bits := physicalHead
    // No authorization metadata escapes into the cache, MMIO fabric or page-walk arbiter.
    io.physical.request.bits.precheckedLoad := false.B
    io.physical.request.bits.translationEpoch := 0.U
    // Reconstruct with the captured fault only. The later physicalStale gate did
    // not participate in the old captured hint and must not change its value.
    io.physical.request.bits.prefetchNextAllowed := (if (p.dataNextLinePrefetch)
        checked.map { stage =>
            val base = stage.deq.bits.request.prefetchNextAllowed
            val allowed = if (registerNextLineDecision)
                base && !PmpDecisionSummary.denied(stage.deq.bits.nextLineDecision.get) else base
            if (factorCheckedNextAllowed) allowed && !stage.deq.bits.fault else allowed
        }.getOrElse(nextAllowed) else false.B)
    owners.io.enq.valid := physicalValid && physicalReady
    owners.io.enq.bits.fault := physicalFault
    owners.io.enq.bits.pageFault := physicalPageFault
    owners.io.enq.bits.precheckedLoad := physicalHead.precheckedLoad
    io.physicalRequest := io.physical.request.fire
    io.posted.foreach { posted =>
        posted.requestProof := checked.get.deq.bits.postedProof.get
        posted.requestProof.valid := io.physical.request.valid && checked.get.deq.bits.postedProof.get.valid
        when(io.physical.request.valid && posted.requestProof.valid) {
            assert(posted.requestProof.bits.finalChecked && posted.requestProof.bits.legacyPostedAccepted &&
                posted.requestProof.bits.epoch === postedEpoch.get && !authorizationChanged)
        }
        PostedStoreCpu.held(io.physical.request, posted.requestProof)
    }

    p.cpuReturnConfig match {
        case None => CpuReturnTransport.orderedOwners(owners, new TranslationResponseOwner, entries, flow = false)
        case Some(config) =>
            val valid = RegInit(VecInit(Seq.fill(config.tableEntries)(false.B)))
            val metadata = Reg(Vec(config.tableEntries, new TranslationResponseOwner))
            val incomingHandle = physicalHead.returnHandle.get
            val physicalHandle = io.physical.response.bits.returnHandle.get
            val faultMask = VecInit((0 until config.tableEntries).map(i => valid(i) && metadata(i).fault))
            val faultLive = faultMask.asUInt.orR
            val faultHandle = PriorityEncoder(faultMask)
            val responseHandle = Mux(faultLive, faultHandle, physicalHandle)
            val count = PopCount(valid)
            // A checked local fault waits behind all older physical owners, then
            // owns an exclusive response interval. The checked head blocks younger work.
            owners.io.enq.ready := config.legal(incomingHandle) && !valid(incomingHandle) &&
                count < entries.U && !faultLive && (!physicalFault || count === 0.U)
            owners.io.deq.valid := valid(responseHandle)
            owners.io.deq.bits := metadata(responseHandle)
            owners.io.count := count
            io.virtual.response.bits.returnHandle.get := responseHandle
            when(owners.io.enq.fire) {
                assert(!valid(incomingHandle), "translation owner handle reused before actual reply")
                valid(incomingHandle) := true.B
                metadata(incomingHandle) := owners.io.enq.bits
            }
            when(owners.io.deq.fire) { valid(responseHandle) := false.B }
            when(io.physical.response.valid) {
                val entering = io.physical.request.fire && physicalHandle === incomingHandle
                assert(!faultLive && config.legal(physicalHandle) &&
                    ((valid(physicalHandle) && !metadata(physicalHandle).fault) || entering),
                    "physical return lost its exact nonfault translation owner")
            }
            assert(count <= entries.U && PopCount(faultMask) <= 1.U)
            when(faultLive) { assert(count === 1.U && !io.physical.request.fire) }
            CpuReturnTransport.held(io.virtual.response)
    }
    val owner = owners.io.deq.bits
    io.virtual.response.valid := owners.io.deq.valid &&
        (owner.fault || io.physical.response.valid)
    CpuReturnTransport.responsePayload(io.virtual.response.bits, io.physical.response.bits)
    if (!p.taggedStoreReturns) { io.virtual.response.bits := io.physical.response.bits }
    when(owner.fault) {
        io.virtual.response.bits.data := 0.U
        io.virtual.response.bits.error := true.B
        io.virtual.response.bits.pageFault := owner.pageFault
    }
    io.physical.response.ready := owners.io.deq.valid && !owner.fault && io.virtual.response.ready
    owners.io.deq.ready := io.virtual.response.fire
    if (p.virtualRamLoadPrecheck) {
        val accepted = RegInit(0.U(8.W))
        val push = io.virtual.request.fire && io.virtual.request.bits.precheckedLoad
        val pop = io.virtual.response.fire && owner.precheckedLoad
        when(push =/= pop) { accepted := Mux(push, accepted + 1.U, accepted - 1.U) }
        when(authorizationChanged || io.precheckFlush.get) {
            assert(accepted === 0.U,
                "VM/PMP/SFENCE context changes must drain accepted prechecked loads before changing authorization")
        }
        when(pop) { assert(accepted =/= 0.U, "prechecked responses retain their ingress owner") }
    }
    io.pageFault := io.virtual.response.fire && owner.fault && owner.pageFault
    io.idle := !waiting && !translated.io.deq.valid && owners.io.count === 0.U &&
        checked.map(stage => !stage.deq.valid).getOrElse(true.B) &&
        virtualRequests.map(stage => !stage.io.deq.valid).getOrElse(true.B)
    if (p.canonicalVirtualStoreOverlap) {
        when(authorizationChanged || io.precheckFlush.get) {
            assert(io.idle,
                "VM/PMP/SFENCE changes must drain accepted canonical stores and overlapping adapter work")
        }
    }
    // Candidate-only assertions follow the legacy implementation so the disabled
    // topology also preserves existing assertion diagnostic source positions.
    require(!p.combinedCheckedDataFlow || (translationHitFlow && p.precheckedDataRequestFlow &&
        registerCheckedRequests && p.registeredTranslationHeads && !queuedHeadSelection && !registerCanonicalStoreEvent),
        "combined checked flow retains both sources and the non-flow checked register")
    if (p.combinedCheckedDataFlow || p.registeredRawCertifiedFlow) {
        val stage = checked.get
        val offers = if (certifiedLoadIngress) VecInit(Seq(identityOffer, precheckedOffer, physicalIngressOffer,
            translationHitOffer, frozenCheckedOffer, certifiedIngressOffer))
        else VecInit(Seq(identityOffer, precheckedOffer, physicalIngressOffer,
            translationHitOffer, frozenCheckedOffer))
        assert(PopCount(offers) <= 1.U,
            "combined checked sources are mutually exclusive for one ingress owner")
        when(incoming.fire) {
            // A delayed demand walk accepts ownership but has no translated result yet.
            // Every immediately available result goes to exactly one registered boundary.
            when(!active || io.translation.response.fire) {
                val direct = identityPass || precheckedPass || translationHitPass || frozenCheckedPass
                assert(translated.io.enq.fire ^ direct,
                    "combined immediate ingress transfers exactly once to checked or translated storage")
                when(direct) {
                    assert(stage.enq.fire && !translated.io.deq.valid,
                        "combined direct ingress cannot bypass an older translated owner")
                }
            }.otherwise {
                assert(!translated.io.enq.fire && !precheckedPass && !translationHitPass &&
                    !identityPass && !frozenCheckedPass,
                    "combined delayed translation retains demand ownership without an immediate transfer")
            }
        }
        when(precheckedOffer && !stage.enq.ready) {
            assert(incoming.fire && translated.io.enq.fire && !precheckedPass &&
                !io.translation.request.fire,
                "combined blocked certified PA spills exactly once without demand retranslation")
        }
        when(precheckedPass) {
            assert(incoming.fire && stage.enq.fire && !translationHitPass && !identityPass &&
                !io.translation.request.fire && !translated.io.enq.fire &&
                stage.enq.bits.request.precheckedLoad && stage.enq.bits.request.address === incoming.bits.address,
                "combined certified PA retains its exact registered ingress and checked authorization")
        }
        when(precheckedPass) {
            assert(!io.canonicalStoreCertificate.get.valid,
                "combined certified load cannot create a canonical store event")
        }
        when(io.canonicalStoreCertificate.get.valid) {
            assert(stage.enq.fire && !precheckedOffer && !precheckedPass &&
                request.write && !request.atomic && !request.precheckedLoad &&
                head.canonicalStoreOrigin.get.valid && !frozenCheckedPass &&
                (translated.io.deq.fire || translationHitPass),
                "combined canonical event belongs only to an accepted raw ordinary store result")
        }
    }
    if (p.registeredRawCertifiedFlow) {
        val stage = checked.get
        assert(!translationHitOffer && !translationHitPass,
            "registered raw demand never bypasses its translation-result register")
        when(precheckedPass) {
            assert(!translated.io.deq.valid && head.asUInt === certifiedHead.get.asUInt &&
                !head.canonicalStoreOrigin.get.valid && !io.translation.request.fire,
                "certified checked transfer uses only its registered ingress descriptor")
        }
        when(io.canonicalStoreCertificate.get.valid) {
            assert(translated.io.deq.fire && stage.enq.fire && !precheckedPass,
                "registered raw canonical event belongs only to the accepted FIFO head")
        }
    }
    if (certifiedLoadIngress) {
        val ingress = virtualRequests.get.io
        val stage = checked.get
        val oldOffers = identityOffer || precheckedOffer || physicalIngressOffer ||
            translationHitOffer || frozenCheckedOffer || translated.io.deq.valid
        when(certifiedIngressNominal) {
            assert(!oldOffers && !incoming.valid && !waiting &&
                head.asUInt === certifiedIngressDescriptor.get.result.asUInt,
                "nominal certified ingress owns the selected descriptor independently of authorization")
        }
        when(io.virtual.request.fire) {
            if (p.coexistingPhysicalLoadIngress) {
                assert(PopCount(VecInit(Seq(ingress.enq.fire, physicalIngressPass, certifiedIngressPass))) === 1.U,
                    "upstream acceptance has exactly one ingress, ordinary checked or certified checked sink")
            } else {
                assert(ingress.enq.fire ^ certifiedIngressPass,
                    "upstream acceptance has exactly one registered ingress or certified checked sink")
            }
        }
        when(certifiedIngressPass) {
            val expected = WireDefault(io.virtual.request.bits)
            expected.prefetchNextAllowed := stage.enq.bits.request.prefetchNextAllowed
            assert(io.virtual.request.fire && stage.enq.fire && !stage.enq.bits.fault &&
                !stage.enq.bits.pageFault && !ingress.enq.fire && !incoming.fire &&
                !translated.io.enq.fire && !translated.io.deq.fire &&
                !io.translation.request.fire && !io.translation.response.fire &&
                stage.enq.bits.request.asUInt === expected.asUInt &&
                head.privilege === io.vmState.dataPrivilege,
                "certified ingress transfers the exact final-port load once through full checked authorization")
            io.canonicalStoreCertificate.foreach(event => assert(!event.valid,
                "certified ingress cannot create a store certificate"))
            stage.enq.bits.postedProof.foreach(proof => assert(!proof.valid,
                "certified ingress carries no posted store authority"))
        }
        when(certifiedIngressNominal && !certifiedIngressPass) {
            assert(io.virtual.request.fire && ingress.enq.fire && !stage.enq.fire &&
                !incoming.fire && !translated.io.enq.fire,
                "denied or blocked nominal ingress falls back intact, without a checked capture")
        }
        assert(io.virtual.request.ready === ingress.enq.ready,
            "certified ingress preserves occupancy-only upstream credit")
    }
    if (p.guardedNaturalDataPmp) {
        val stage = checked.get
        when(stage.enq.fire && guardedCheckedAlignmentFault.get) {
            assert(stage.enq.bits.fault && !stage.enq.bits.request.prefetchNextAllowed,
                "guarded natural data PMP rejects malformed checked requests without hint authority")
            assert(!io.canonicalStoreCertificate.get.valid,
                "guarded natural data PMP never certifies a malformed request")
        }
        when(io.physical.request.valid) {
            assert(AlignedMemoryDisjoint.aligned(io.physical.request.bits.address, io.physical.request.bits.size),
                "guarded natural data PMP preserves original aligned physical requests")
        }
    }

    if (p.coexistingPhysicalLoadIngress) {
        val ingress = virtualRequests.get.io
        val stage = checked.get
        val offered = io.virtual.request.bits
        assert(!(physicalIngressOffer && certifiedIngressNominal),
            "ordinary physical and certified ingress cannot select the same final-port owner")
        assert(io.virtual.request.ready === ingress.enq.ready,
            "ordinary ingress retains old-occupancy credit without physical-ready borrowing")
        when(physicalIngressPass) {
            val expected = WireDefault(offered)
            expected.prefetchNextAllowed := stage.enq.bits.request.prefetchNextAllowed
            assert(io.virtual.request.fire && stage.enq.fire && !stage.enq.bits.fault &&
                !stage.enq.bits.pageFault && !ingress.enq.fire && !incoming.fire &&
                !translated.io.enq.fire && !translated.io.deq.fire && !waiting &&
                !io.translation.request.fire && !io.translation.response.fire && !certifiedIngressPass &&
                stage.enq.bits.request.asUInt === expected.asUInt,
                "ordinary registered ingress transfers one exact request through checked, never a new authority")
            io.canonicalStoreCertificate.foreach(event => assert(!event.valid,
                "ordinary physical read ingress cannot create canonical store authority"))
            stage.enq.bits.postedProof.foreach(proof => assert(!proof.valid,
                "ordinary physical read ingress cannot carry posted store authority"))
        }
        when(coexistingPhysicalIngressNominal && !physicalIngressPass) {
            assert(io.virtual.request.fire && ingress.enq.fire && !stage.enq.fire &&
                !incoming.fire && !translated.io.enq.fire && !certifiedIngressPass,
                "blocked ordinary ingress spills once into the original registered fallback")
            assert(ingress.enq.bits.request.asUInt === offered.asUInt &&
                ingress.enq.bits.context.asUInt === io.vmState.asUInt,
                "ordinary ingress spill retains the exact original request and accepted context")
        }
    }

}
