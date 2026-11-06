package soc.core.inorder

import chisel3._
import chisel3.util._

/** One native owner with host Sv39 or nested VS/G translation. Reuse the
  * existing read-only Svade walker and its bounded TLB at both guest stages.
  * Every VS PTE read passes G-stage translation; every resulting supervisor
  * physical access passes PMP. HFENCE globally invalidates these small TLBs.
  * The shared physical D-cache still owns every PTW read and real response.
  */
class I1HypervisorTranslation(p: FiveStageConfig, instruction: Boolean,
    parallelInstructionCandidates: Boolean = false, parallelDataCandidates: Boolean = false,
    registeredInstructionReturn: Boolean = false) extends Module {
    require(p.withH)
    val io = IO(new FiveStageTranslationIO(p, instruction,
        parallelInstructionCandidates, parallelDataCandidates))
    val host = Module(new FiveStageAddressTranslation(p, instruction,
        parallelInstructionCandidates, parallelDataCandidates, registeredInstructionReturn))
    // VS PPNs are guest physical, up to 56 bits in a PTE. G-stage checks its
    // own unsigned 41-bit input before actual physical-width/PMP checks.
    val vsConfig = p.copy(physicalAddressBits = 56, pmpEntries = 0,
        fastInstructionTranslation = false, fastDataTranslation = false,
        overlapDataRetirement = false, readOnlyDataRetirement = false, directFastDataIssue = false,
        indexedDataProofs = false, bankedTlbProofs = false, dataReplyHandoff = false)
    val gConfig = p.copy(fastInstructionTranslation = false, fastDataTranslation = false,
        overlapDataRetirement = false, readOnlyDataRetirement = false, directFastDataIssue = false,
        indexedDataProofs = false, bankedTlbProofs = false, dataReplyHandoff = false)
    val vs = Module(new FiveStageAddressTranslation(vsConfig, instruction, firstStage = true))
    val guest = Module(new FiveStageAddressTranslation(gConfig, instruction = false, guestPhysicalStage = true))
    val active = RegInit(false.B); val guestOwner = Reg(Bool()); val bypassOwner = Reg(Bool())
    val bypassOfferHeld = RegInit(false.B)
    val candidateGuest = if (instruction) io.context.guest.get.virtualized else
        io.context.guest.get.dataVirtualized || io.request.bits.guest.get.force
    val effectivePrivilege = if (instruction) io.context.privilege else io.context.dataPrivilege
    val bare = effectivePrivilege === 3.U || io.context.satp(63, 60) === 0.U
    val address = io.request.bits.address
    val fits = if (p.physicalBits < 64) !address(63, p.physicalBits).orR else true.B
    val aligned = MuxLookup(io.request.bits.size, false.B)(Seq(0.U -> true.B,
        1.U -> !address(0), 2.U -> !address(1, 0).orR, 3.U -> !address(2, 0).orR))
    val normalVector = !io.request.bits.guest.get.vector ||
        I1AddressWindow.contains(address, p.cacheableBase, p.cacheableBytes)
    // With no PMP bank, an aligned physical interval in M/Bare needs no
    // translation transaction. The ordinary cache/atomic owner already
    // provides backpressure and the real completion, including stores.
    val directPolicy = (p.pmpEntries == 0).B && !candidateGuest && bare
    val candidateBypass = directPolicy && fits && aligned && normalVector
    // A host fast lookup may retain a physical offer BEFORE upstream fire.
    // Bind that offer through a later context change, just like a held bypass.
    val hostOfferHeld = !active && host.io.registeredOwner
    val selectBypass = !hostOfferHeld && (bypassOfferHeld || candidateBypass)
    val selectGuest = !hostOfferHeld && !bypassOfferHeld && candidateGuest
    val bypassRoom = !active || bypassOwner
    val slot = !active || io.response.fire
    host.io.request.valid := io.request.valid && slot && !selectGuest && !selectBypass
    vs.io.request.valid := io.request.valid && slot && selectGuest
    host.io.request.bits := io.request.bits; vs.io.request.bits := io.request.bits
    io.request.ready := Mux(selectBypass, bypassRoom && io.physical.request.ready,
        slot && Mux(selectGuest, vs.io.request.ready, host.io.request.ready))
    when(io.response.fire) { active := false.B }
    when(io.request.fire) {
        active := true.B; guestOwner := selectGuest; bypassOwner := selectBypass
        bypassOfferHeld := false.B
    }
    val routeBypass = Mux(active, bypassOwner, selectBypass)
    val routeGuest = Mux(active, guestOwner, selectGuest)
    // Prepare PA before range/alignment permission and READY. An invalid
    // physical offer still enters the host fault owner; it cannot access RAM.
    val directPayload = !hostOfferHeld && (bypassOfferHeld || directPolicy)
    val routeDirectPayload = Mux(active, bypassOwner, directPayload)
    // Only the RETURNING word owns turnover. A new address/privilege check
    // must not feed back through parcel admission into the fetch PC enable.
    io.bareTurnover.foreach(_ := active && bypassOwner)
    host.io.context := io.context; host.io.entries := io.entries
    host.io.invalidate := io.invalidate
    host.io.addressCandidates.foreach(_ := io.addressCandidates.get)
    host.io.candidateSecond.foreach(_ := io.candidateSecond.get)
    host.io.dataCandidates.foreach(_ := io.dataCandidates.get)
    host.io.dataCandidateEarly.foreach(_ := io.dataCandidateEarly.get)
    host.io.readAhead.foreach(_ := io.readAhead.get)
    val vsContext = WireDefault(io.context)
    val ordinaryPrivilege = if (instruction) io.context.privilege else io.context.dataPrivilege
    val guestPrivilege = Mux(io.request.bits.guest.get.force,
        io.context.guest.get.guestPrivilege, ordinaryPrivilege)
    vsContext.privilege := guestPrivilege; vsContext.dataPrivilege := guestPrivilege
    vsContext.satp := io.context.guest.get.vsatp
    vsContext.sum := io.context.guest.get.sum
    vsContext.mxr := io.context.mxr || io.context.guest.get.mxr
    vsContext.pmpAllOff := true.B
    vs.io.context := vsContext; vs.io.entries := DontCare; vs.io.invalidate := io.invalidate
    val ownerContext = RegEnable(io.context, io.request.fire && selectGuest)
    val gContext = WireDefault(ownerContext)
    gContext.privilege := 0.U; gContext.dataPrivilege := 0.U
    gContext.satp := ownerContext.guest.get.hgatp
    gContext.sum := false.B; gContext.mxr := ownerContext.mxr
    guest.io.context := gContext; guest.io.entries := io.entries; guest.io.invalidate := io.invalidate

    // VS has mutually exclusive PTE and final-access offers. Bind the G-stage
    // response to that accepted source through its complete physical access.
    val vsWalkOffer = vs.io.walk.request.valid
    guest.io.request.valid := vs.io.walk.request.valid || vs.io.physical.request.valid
    guest.io.request.bits := Mux(vsWalkOffer, vs.io.walk.request.bits, vs.io.physical.request.bits)
    guest.io.request.bits.guest.get.force := false.B
    guest.io.request.bits.guest.get.execute := !vsWalkOffer &&
        (instruction.B || vs.io.physical.request.bits.guest.get.execute)
    guest.io.request.bits.guest.get.fetch := !vsWalkOffer && instruction.B
    vs.io.walk.request.ready := guest.io.request.ready && vsWalkOffer
    vs.io.physical.request.ready := guest.io.request.ready && !vsWalkOffer
    val gWalkOwner = Reg(Bool()); val guestAddress = Reg(UInt(64.W))
    when(guest.io.request.fire) { gWalkOwner := vsWalkOffer; guestAddress := guest.io.request.bits.address }
    vs.io.walk.response.valid := guest.io.response.valid && gWalkOwner
    vs.io.physical.response.valid := guest.io.response.valid && !gWalkOwner
    vs.io.walk.response.bits := guest.io.response.bits
    vs.io.physical.response.bits := guest.io.response.bits
    guest.io.response.ready := Mux(gWalkOwner, vs.io.walk.response.ready, vs.io.physical.response.ready)
    val fault = RegInit(0.U.asTypeOf(new I1GuestFault))
    when(io.request.fire) { fault := 0.U.asTypeOf(new I1GuestFault) }
    when(guest.io.response.fire && guest.io.response.bits.error && guest.io.response.bits.pageFault) {
        fault.pageFault := true.B
        // Sv39x4 supports 41-bit GPAs. For an out-of-range GPA, HTVAL=0
        // is architecturally allowed; never publish a truncated alias.
        fault.physical := Mux(guestAddress(63, 41).orR, 0.U, guestAddress(40, 2))
        fault.implicitPte := gWalkOwner
    }

    // Final guest demand goes to the normal instruction/data physical port.
    // A translated VS PTE read and a G PTE read use the existing PTW port.
    val guestWalk = guest.io.walk.request.valid
    val localWalk = Wire(Decoupled(new FiveStageDataRequest(p)))
    val localWalkResponse = Wire(Decoupled(new FiveStageDataResponse(p)))
    localWalk.valid := guestWalk || guest.io.physical.request.valid && gWalkOwner
    localWalk.bits := Mux(guestWalk, guest.io.walk.request.bits, guest.io.physical.request.bits)
    guest.io.walk.request.ready := localWalk.ready && guestWalk
    val physical = guest.io.physical
    io.physical.request.valid := Mux(routeGuest,
        physical.request.valid && !gWalkOwner, host.io.physical.request.valid)
    io.physical.request.bits := Mux(routeGuest, physical.request.bits, host.io.physical.request.bits)
    // These are authorized SYSTEM physical addresses. Keep original VA/GPA
    // in the native/fault owners; unused high PA bits need no cache/AMO mux.
    io.physical.request.bits.address := Mux(routeGuest,
        physical.request.bits.address(p.physicalBits - 1, 0),
        host.io.physical.request.bits.address(p.physicalBits - 1, 0))
    host.io.physical.request.ready := io.physical.request.ready && !routeGuest
    physical.request.ready := Mux(gWalkOwner, localWalk.ready && !guestWalk,
        io.physical.request.ready && routeGuest)
    host.io.physical.response.valid := io.physical.response.valid && !routeGuest
    host.io.physical.response.bits := io.physical.response.bits
    val externalWalkOwner = Reg(Bool())
    when(localWalk.fire) { externalWalkOwner := guestWalk }
    guest.io.walk.response.valid := localWalkResponse.valid && externalWalkOwner
    guest.io.walk.response.bits := localWalkResponse.bits
    physical.response.valid := Mux(gWalkOwner, localWalkResponse.valid && !externalWalkOwner,
        io.physical.response.valid && routeGuest)
    physical.response.bits := Mux(gWalkOwner, localWalkResponse.bits, io.physical.response.bits)
    localWalkResponse.ready := Mux(externalWalkOwner, guest.io.walk.response.ready, physical.response.ready)
    io.physical.response.ready := Mux(routeGuest, physical.response.ready, host.io.physical.response.ready)
    io.walk.request.valid := Mux(routeGuest, localWalk.valid, host.io.walk.request.valid)
    io.walk.request.bits := Mux(routeGuest, localWalk.bits, host.io.walk.request.bits)
    io.walk.request.bits.address := Mux(routeGuest,
        localWalk.bits.address(p.physicalBits - 1, 0),
        host.io.walk.request.bits.address(p.physicalBits - 1, 0))
    localWalk.ready := io.walk.request.ready && routeGuest
    host.io.walk.request.ready := io.walk.request.ready && !routeGuest
    localWalkResponse.valid := io.walk.response.valid && routeGuest
    localWalkResponse.bits := io.walk.response.bits
    host.io.walk.response.valid := io.walk.response.valid && !routeGuest
    host.io.walk.response.bits := io.walk.response.bits
    io.walk.response.ready := Mux(routeGuest, localWalkResponse.ready, host.io.walk.response.ready)
    // Decode the registered return owner once. Direct cache data then crosses
    // one parallel owner mux rather than the serial host/VS/direct overrides.
    // Live VALID/READY still qualify consumption, never the wide payload route.
    val returnDirect = active && bypassOwner
    val returnGuest = active && !bypassOwner && guestOwner
    val returnHost = active && !bypassOwner && !guestOwner
    io.response.valid := returnDirect && io.physical.response.valid ||
        returnGuest && vs.io.response.valid || returnHost && host.io.response.valid
    io.response.bits := Mux1H(Seq(returnDirect -> io.physical.response.bits,
        returnGuest -> vs.io.response.bits, returnHost -> host.io.response.bits))
    // The registered owner selects data. Publication and all control fields
    // retain their live qualification, so no extra load cycle is introduced.
    io.response.bits.data := Mux1H(Seq(bypassOwner -> io.physical.response.bits.data,
        (!bypassOwner && guestOwner) -> vs.io.response.bits.data,
        (!bypassOwner && !guestOwner) -> host.io.response.bits.data))
    // Predecoded parcel length travels with the same registered data owner.
    // Active/VALID still govern publication, not these unowned payload bits.
    io.response.bits.parcelClasses.foreach(_ := Mux1H(Seq(
        bypassOwner -> io.physical.response.bits.parcelClasses.get,
        (!bypassOwner && guestOwner) -> vs.io.response.bits.parcelClasses.get,
        (!bypassOwner && !guestOwner) -> host.io.response.bits.parcelClasses.get)))
    io.response.bits.guest.get := Mux(returnGuest, fault, 0.U.asTypeOf(new I1GuestFault))
    io.response.bits.fetchSpan := returnDirect && instruction.B || returnHost && host.io.response.bits.fetchSpan
    io.response.bits.pageFault := returnGuest && vs.io.response.bits.pageFault && !fault.pageFault ||
        returnHost && host.io.response.bits.pageFault
    host.io.response.ready := returnHost && io.response.ready
    vs.io.response.ready := returnGuest && io.response.ready
    io.registeredOwner := active || bypassOfferHeld || host.io.registeredOwner || vs.io.registeredOwner || guest.io.registeredOwner
    io.hit := host.io.hit || vs.io.hit; io.miss := host.io.miss || vs.io.miss
    io.physicalCacheable.foreach(_ := Mux(routeGuest,
        !physical.request.bits.noAllocate && I1AddressWindow.contains(physical.request.bits.address,
            p.cacheableBase, p.cacheableBytes), host.io.physicalCacheable.get))
    when(routeDirectPayload) {
        io.physical.request.bits := io.request.bits
        io.physical.request.bits.address := address(p.physicalBits - 1, 0)
        io.physicalCacheable.foreach(_ := !io.request.bits.noAllocate &&
            I1AddressWindow.contains(address, p.cacheableBase, p.cacheableBytes))
    }
    when(routeBypass) {
        io.physical.request.valid := io.request.valid && selectBypass && bypassRoom
        io.physical.response.ready := active && bypassOwner && io.response.ready
        host.io.physical.request.ready := false.B; physical.request.ready := false.B
        host.io.physical.response.valid := false.B; physical.response.valid := false.B
    }
    when(routeBypass && io.physical.request.valid && !io.physical.request.ready) {
        bypassOfferHeld := true.B
    }
    when(io.request.fire) { bypassOfferHeld := false.B }
    io.ordinaryStoreAccepted.foreach(_ :=
        routeBypass && io.physical.request.fire && io.physical.request.bits.write &&
            !io.physical.request.bits.atomic || host.io.ordinaryStoreAccepted.get ||
        routeGuest && !gWalkOwner && physical.request.fire && physical.request.bits.write &&
            !physical.request.bits.atomic)
    when(!reset.asBool) {
        when(!active && routeDirectPayload && !selectBypass) {
            assert(!io.physical.request.valid, "unqualified direct PA escaped its host fault owner")
        }
        when(routeBypass && io.physical.request.fire) {
            assert(io.request.fire && selectBypass, "direct physical request has no native owner")
        }
        when(bypassOfferHeld) { assert(io.request.valid, "held physical offer was withdrawn") }
        assert(!(vs.io.walk.request.valid && vs.io.physical.request.valid), "VS walker lost exclusive source")
        assert(!(guestWalk && physical.request.valid), "G walker lost exclusive physical owner")
    }
}
