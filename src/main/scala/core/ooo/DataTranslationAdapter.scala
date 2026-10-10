package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.bus.TwoEntryRegisterQueue

private[ooo] class VirtualDataRequest(p: OooParams) extends Bundle {
    val request = new DataRequest
    val postedProof = p.postedProofConfig.map(c => Valid(new PostedStoreProof(c)))
    val context = new VmCsrState
}

private[ooo] class TranslatedDataRequest(p: OooParams) extends Bundle {
    val request = new DataRequest
    val postedProof = p.postedProofConfig.map(c => Valid(new PostedStoreProof(c)))
    val privilege = UInt(2.W)
    val checkPhysical = Bool()
    val pageFault = Bool()
    val accessFault = Bool()
}

private[ooo] class TranslationResponseOwner extends Bundle {
    val fault = Bool()
    val pageFault = Bool()
    val precheckedLoad = Bool()
}

private[ooo] class CheckedDataRequest(p: OooParams) extends Bundle {
    val request = new DataRequest
    val postedProof = p.postedProofConfig.map(c => Valid(new PostedStoreProof(c)))
    val fault = Bool()
    val pageFault = Bool()
}

/** In-order DTLB boundary. Hits may enter the translated-request FIFO in the request cycle; a miss blocks new
  * translations, but already translated physical requests and responses continue. The physical port may have multiple
  * requests outstanding. Fault placeholders share its response-order queue without issuing a physical request.
  */
class DataTranslationAdapter(p: OooParams, entries: Int = 8, registerCheckedRequests: Boolean = false) extends Module {
    require(p.virtualMemoryLevels > 0 && Set(4, 8, 16).contains(entries))
    require(!p.postedStoreMerge || registerCheckedRequests,
        "posted proof needs the common registered checked boundary before every MMIO router")
    require(!p.virtualRamLoadPrecheck || registerCheckedRequests,
        "virtual load precheck requires a registered physical authorization boundary")
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
        val virtual = Flipped(new DataPort)
        val physical = new DataPort
        val posted = p.postedProofConfig.map(c => new PostedStoreTranslationPort(c))
        val translation = new SvTranslationPort
        val loadPrecheck = if (p.virtualRamLoadPrecheck) Some(Flipped(new VirtualLoadPrecheckPort)) else None
        val translationPeek = if (p.virtualRamLoadPrecheck) Some(new SvTranslationPeekPort) else None
        val precheckFlush = if (p.virtualRamLoadPrecheck) Some(Input(Bool())) else None
        val vmState = Input(new VmCsrState)
        val pmpState = Input(new PmpState)
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
        // Derived 65-bit PMP region bounds are not additional architectural state. Snapshot only
        // the implemented cfg/address CSRs, avoiding a second register bank for decoded ranges.
        val pmpContext = Cat(io.pmpState.cfg.take(p.pmpEntries).reverse.map(_.asUInt) ++
            io.pmpState.addr.take(p.pmpEntries).reverse.map(_.asUInt))
        val previousPmp = RegInit(0.U(pmpContext.getWidth.W))
        val changed = previousVm.asUInt =/= io.vmState.asUInt || previousPmp =/= pmpContext
        previousVm := io.vmState
        previousPmp := pmpContext
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
            io.vmState.dataPrivilege =/= 3.U && io.vmState.satp(63, 60) =/= 0.U
        peek.request.bits.virtualAddress := precheck.request.bits.address
        peek.request.bits.rootPpn := io.vmState.satp(43, 0)
        peek.request.bits.asid := io.vmState.satp(59, 44)
        peek.request.bits.mode := io.vmState.satp(63, 60)
        peek.request.bits.privilege := io.vmState.dataPrivilege
        peek.request.bits.access := PmpAccess.read
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

    // Registered queue boundaries keep the TLB CAM/PMP/TileLink arbitration off one FPGA combinational path.
    val translated = Module(new Queue(new TranslatedDataRequest(p), entries, pipe = false, flow = false))
    val owners = Module(new Queue(new TranslationResponseOwner, entries, pipe = false, flow = false))
    val waiting = RegInit(false.B)
    val savedRequest = Reg(new DataRequest)
    val savedProof = p.postedProofConfig.map(c => Reg(Valid(new PostedStoreProof(c))))
    val savedPrivilege = Reg(UInt(2.W))
    // Register the actual virtual ingress, not merely the translated egress.
    // Capture the architectural context at upstream acceptance; a queued request
    // must not inherit a later SATP/SUM/MXR/privilege value. PMP remains checked
    // at the existing physical authorization boundary. CPU fences drain accepted
    // memory, and idle includes this queue for all integrating clients.
    val physicalIngressPass = WireDefault(false.B)
    val virtualRequests = if (p.registeredTranslationHeads)
        Some(Module(new TwoEntryRegisterQueue(new VirtualDataRequest(p)))) else None
    virtualRequests.foreach { stage =>
        stage.io.enq.valid := io.virtual.request.valid && !physicalIngressPass
        stage.io.enq.bits.request := io.virtual.request.bits
        stage.io.enq.bits.context := io.vmState
        stage.io.enq.bits.postedProof.foreach(_ := io.posted.get.upstreamProof)
        io.virtual.request.ready := stage.io.enq.ready
    }
    val incoming = virtualRequests.map { stage =>
        val request = Wire(Decoupled(new DataRequest))
        request.valid := stage.io.deq.valid
        request.bits := stage.io.deq.bits.request
        stage.io.deq.ready := request.ready
        request
    }.getOrElse(io.virtual.request)
    val incomingProof = p.postedProofConfig.map { _ =>
        virtualRequests.map(_.io.deq.bits.postedProof.get).getOrElse(io.posted.get.upstreamProof)
    }
    val context = virtualRequests.map(_.io.deq.bits.context).getOrElse(io.vmState)
    val active = incoming.bits.virtualized && !incoming.bits.precheckedLoad
    val canAccept = !waiting && translated.io.enq.ready
    val identityOffer = if (p.identityDataRequestFlow)
        incoming.valid && !active && !incoming.bits.precheckedLoad && canAccept && !translated.io.deq.valid else false.B
    val identityPass = WireDefault(false.B)
    // A certified load already carries its PA at the registered ingress. It can
    // share the empty translated-queue shortcut, but must still use the full
    // PMP/epoch/shape/range authorization below. Older translated work wins.
    val precheckedOffer = if (p.precheckedDataRequestFlow)
        incoming.valid && incoming.bits.precheckedLoad && canAccept && !translated.io.deq.valid else false.B
    val precheckedPass = WireDefault(false.B)
    // The CPU has already checked ordinary physical load permissions before its
    // registered request FIFO. With no older ingress/translated/walker owner, an
    // aligned in-aperture read may enter checked directly. No request can reach
    // the physical port without that register, and a blocked checked queue spills
    // the accepted request into virtualRequests rather than losing/reoffering it.
    // Stores, atomics, MMIO, uncached and virtual/certified accesses stay staged.
    val physicalIngressOffer = if (p.physicalLoadIngressFlow) {
        val offered = io.virtual.request.bits
        io.virtual.request.valid && virtualRequests.get.io.enq.ready &&
            !virtualRequests.get.io.deq.valid && !translated.io.deq.valid && !waiting &&
            !offered.virtualized && !offered.precheckedLoad && !offered.write && !offered.atomic &&
            !offered.uncached && AlignedMemoryDisjoint.aligned(offered.address, offered.size) &&
            SpeculativeRamRange.contains(p, offered.address, offered.size)
    } else false.B

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
    translated.io.enq.valid := (!waiting && incoming.valid && !active && !identityPass && !precheckedPass) || translatedReply
    val original = Mux(waiting, savedRequest, incoming.bits)
    translated.io.enq.bits := 0.U.asTypeOf(new TranslatedDataRequest(p))
    translated.io.enq.bits.request := original
    translated.io.enq.bits.postedProof.foreach(_ := Mux(waiting, savedProof.get, incomingProof.get))
    translated.io.enq.bits.request.address := Mux(active || waiting,
        io.translation.response.bits.physicalAddress, original.address)
    translated.io.enq.bits.request.virtualized := false.B
    translated.io.enq.bits.request.uncached := original.uncached ||
        ((active || waiting) && io.translation.response.bits.pbmt =/= 0.U)
    translated.io.enq.bits.privilege := Mux(waiting, savedPrivilege, context.dataPrivilege)
    translated.io.enq.bits.checkPhysical := active || waiting || original.precheckedLoad
    translated.io.enq.bits.pageFault := (active || waiting) && io.translation.response.bits.pageFault
    translated.io.enq.bits.accessFault := ((active || waiting) && io.translation.response.bits.accessFault) ||
        staleAuthorization(original) || (original.precheckedLoad &&
            (original.virtualized || original.write || original.atomic || original.uncached ||
                context.dataPrivilege === 3.U || context.satp(63, 60) === 0.U))

    when(io.translation.request.fire && !io.translation.response.fire) {
        waiting := true.B
        savedRequest := incoming.bits
        savedProof.foreach(_ := incomingProof.get)
        savedPrivilege := context.dataPrivilege
    }
    when(waiting && io.translation.response.fire) { waiting := false.B }

    // Both sources are registered. No TLB lookup or memory ready signal feeds
    // this selection, and authorization still ends at the checked register.
    val head = if (p.precheckedDataRequestFlow)
        Mux(precheckedOffer, translated.io.enq.bits, translated.io.deq.bits) else translated.io.deq.bits
    val request = head.request
    val pmp = Module(new PmpChecker(p.pmpEntries))
    pmp.io.state := io.pmpState
    pmp.io.address := request.address
    pmp.io.size := request.size
    pmp.io.privilege := head.privilege
    pmp.io.access := Mux(request.atomic,
        Mux(request.atomicOp === 2.U, PmpAccess.read,
            Mux(request.atomicOp === 3.U, PmpAccess.write, PmpAccess.readWrite)),
        Mux(request.write, PmpAccess.write, PmpAccess.read))
    val atomicOutside = request.atomic && head.checkPhysical &&
        !SpeculativeRamRange.contains(p, request.address, request.size)
    val precheckedShapeFault = if (p.precheckedDataRequestFlow) {
        val mask = MuxLookup(request.size, 255.U(8.W))(Seq(0.U -> 1.U, 1.U -> 3.U, 2.U -> 15.U))
        request.precheckedLoad && (!AlignedMemoryDisjoint.aligned(request.address, request.size) ||
            request.mask =/= (mask << request.address(2, 0))(7, 0))
    } else false.B
    val fault = head.pageFault || head.accessFault || precheckedShapeFault ||
        (head.checkPhysical && pmp.io.denied) || atomicOutside || staleAuthorization(request) ||
        (request.precheckedLoad && !SpeculativeRamRange.contains(p, request.address, request.size))
    // Snapshot the request and fault decision before downstream grants.
    // Fault placeholders remain ordered but never issue physical requests.
    val checked: Option[QueueIO[CheckedDataRequest]] = if (registerCheckedRequests)
        Some(if (p.registeredTranslationHeads)
            Module(new TwoEntryRegisterQueue(new CheckedDataRequest(p))).suggestName("checked").io
        else Module(new Queue(new CheckedDataRequest(p), 2, pipe = false, flow = false)).suggestName("checked").io)
    else None
    checked.foreach { stage =>
        if (p.identityDataRequestFlow || p.precheckedDataRequestFlow || p.physicalLoadIngressFlow) {
            // Empty-FIFO pass-through only for an already-physical request.
            // If checked stalls, the identical offer spills into translated,
            // preserving held payload and capacity without a ready path from
            // the external physical port. Older translated work always wins.
            stage.enq.valid := translated.io.deq.valid || identityOffer || precheckedOffer || physicalIngressOffer
            stage.enq.bits.request := Mux(physicalIngressOffer, io.virtual.request.bits,
                Mux(identityOffer, incoming.bits, request))
            stage.enq.bits.fault := Mux(identityOffer || physicalIngressOffer, false.B, fault)
            stage.enq.bits.pageFault := Mux(identityOffer || physicalIngressOffer, false.B, head.pageFault)
            identityPass := identityOffer && stage.enq.ready
            precheckedPass := precheckedOffer && stage.enq.ready
            physicalIngressPass := physicalIngressOffer && stage.enq.ready
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
        translated.io.deq.ready := stage.enq.ready
    }
    // Authorization is captured with the checked request, including the identity
    // queue bypass. The incoming hint is always overwritten, even when disabled.
    val nextAllowed = if (p.dataNextLinePrefetch) {
        val authorize = Module(new NextLineAuthorization(p))
        authorize.io.request := Mux(physicalIngressOffer, io.virtual.request.bits,
            Mux(identityOffer, incoming.bits, request))
        authorize.io.privilege := Mux(physicalIngressOffer, io.vmState.dataPrivilege,
            Mux(identityOffer, context.dataPrivilege, head.privilege))
        authorize.io.pmpState := io.pmpState
        authorize.io.fault := Mux(identityOffer || physicalIngressOffer, false.B, fault)
        authorize.io.allowed
    } else false.B
    checked.foreach(_.enq.bits.request.prefetchNextAllowed := nextAllowed)
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
    io.physical.request.bits.prefetchNextAllowed := (if (p.dataNextLinePrefetch)
        checked.map(_.deq.bits.request.prefetchNextAllowed).getOrElse(nextAllowed) else false.B)
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

    val owner = owners.io.deq.bits
    io.virtual.response.valid := owners.io.deq.valid &&
        (owner.fault || io.physical.response.valid)
    io.virtual.response.bits := io.physical.response.bits
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
    io.idle := !waiting && !translated.io.deq.valid && !owners.io.deq.valid &&
        checked.map(stage => !stage.deq.valid).getOrElse(true.B) &&
        virtualRequests.map(stage => !stage.io.deq.valid).getOrElse(true.B)
}
