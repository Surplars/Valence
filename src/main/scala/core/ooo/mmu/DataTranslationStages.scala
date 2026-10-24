package soc.core.ooo

import chisel3._
import chisel3.util._

/** One accepted translation result, including the request-synchronous ownership
  * sidecars. Ordinary untagged requests keep their existing ordered response
  * ownership; this descriptor does not invent a ROB token or a cache MSHR.
  */
class TranslatedDataRequest(p: OooParams) extends Bundle {
    val request = new DataRequest(p.dataReturnHandleBits)
    val postedProof = p.postedProofConfig.map(c => Valid(new PostedStoreProof(c)))
    val canonicalStoreOrigin = if (p.canonicalVirtualStoreOverlap) Some(Valid(new CanonicalStoreOrigin(p))) else None
    val frozenStorePresent = if (p.frozenStoreProofEnabled) Some(Bool()) else None
    val originalVirtualAddress = if (p.canonicalVirtualStoreOverlap) Some(UInt(64.W)) else None
    val privilege = UInt(2.W)
    val checkPhysical = Bool()
    val pageFault = Bool()
    val accessFault = Bool()
}

/** M2 result boundary: existing capacity, latency one, sustained II one.
  * Ready is occupancy-only. There is neither empty bypass nor full-pop credit
  * borrowing, so downstream PMP/physical READY cannot reach TLB admission.
  * A full queue takes one recovery bubble, then supports simultaneous push/pop
  * every cycle. Context/recovery flush NEVER erases an accepted descriptor.
  */
class DataTranslationResultBuffer(p: OooParams, entries: Int = 8) extends Module {
    require(Set(4, 8, 16).contains(entries))
    val io = IO(new QueueIO(new TranslatedDataRequest(p), entries))
    private val storage = Module(new Queue(new TranslatedDataRequest(p), entries, pipe = false, flow = false))
    io <> storage.io
    val held = RegNext(io.deq.valid && !io.deq.ready, false.B)
    val previous = RegEnable(io.deq.bits, io.deq.valid && !io.deq.ready)
    when(held && !reset.asBool) {
        assert(io.deq.valid && io.deq.bits.asUInt === previous.asUInt,
            "held translation result changed its accepted descriptor")
    }
}

/** Uniform observation view, retaining existing adapter queue taps in both A/B modes. */
class DataTranslationResultStorage(val io: QueueIO[TranslatedDataRequest])

class DataAuthorizationContext extends Bundle {
    val epoch = UInt(32.W)
    val stable = Bool()
    val changing = Bool()
    val flush = Bool()
}

/** Pure permission evaluator: no state, owner, request credit, or response credit.
  * M2 feeds it only the registered result head. The existing checked queue is
  * still the one-cycle capture of the request, fault and prefetch permission.
  * canonical.valid is a qualification preview, NOT a completion/event: the
  * adapter must additionally require exact checked enqueue FIRE and origin route.
  */
class DataPhysicalPermissionEvaluator(p: OooParams, alignedNextLinePmp: Boolean = false,
    factorCheckedNextAllowed: Boolean = false, registerNextLineDecision: Boolean = false) extends Module {
    require(p.registeredDataTranslation && p.virtualRamLoadPrecheck && p.canonicalVirtualStoreOverlap)
    require(!p.precheckedDataRequestFlow && !p.frozenStoreProofEnabled && p.postedProofConfig.isEmpty)
    val io = IO(new Bundle {
        val result = Input(new TranslatedDataRequest(p))
        val authorization = Input(new DataAuthorizationContext)
        val pmpState = Input(new PmpState)
        // Identity requests retain their original shortcut into checked. Their
        // hint request/context is selected atomically, without a TLB bypass.
        val hintRequest = Input(new DataRequest(p.dataReturnHandleBits))
        val hintPrivilege = Input(UInt(2.W))
        val hintBypassFault = Input(Bool())
        val fault = Output(Bool())
        val pmpDenied = Output(Bool())
        val access = Output(UInt(2.W))
        val nextAllowed = Output(Bool())
        val nextDecision = if (registerNextLineDecision) Some(Output(new PmpDecisionSummary(p.pmpEntries))) else None
        val canonical = Output(Valid(new CanonicalStoreCertificate(p)))
    })
    val request = io.result.request
    val pmp = Module(new PmpChecker(p.pmpEntries))
    pmp.io.state := io.pmpState
    pmp.io.address := request.address
    pmp.io.size := request.size
    pmp.io.privilege := io.result.privilege
    pmp.io.access := Mux(request.atomic,
        Mux(request.atomicOp === 2.U, PmpAccess.read,
            Mux(request.atomicOp === 3.U, PmpAccess.write, PmpAccess.readWrite)),
        Mux(request.write, PmpAccess.write, PmpAccess.read))
    io.pmpDenied := pmp.io.denied
    io.access := pmp.io.access
    val inRam = SpeculativeRamRange.contains(p, request.address, request.size)
    val stale = request.precheckedLoad && (request.translationEpoch =/= io.authorization.epoch ||
        io.authorization.changing || io.authorization.flush)
    io.fault := io.result.pageFault || io.result.accessFault ||
        (io.result.checkPhysical && pmp.io.denied) ||
        (request.atomic && io.result.checkPhysical && !inRam) || stale ||
        (request.precheckedLoad && !inRam)

    val nextLineAuthorization = if (p.dataNextLinePrefetch) {
        val authorize = Module(new NextLineAuthorization(p, alignedLinePmp = alignedNextLinePmp,
            exportDecision = registerNextLineDecision))
        CpuReturnTransport.requestPayload(authorize.io.request, io.hintRequest)
        authorize.io.privilege := io.hintPrivilege
        authorize.io.pmpState := io.pmpState
        authorize.io.fault := (if (factorCheckedNextAllowed) false.B else !io.hintBypassFault && io.fault)
        io.nextAllowed := (if (registerNextLineDecision) authorize.eligible.get else authorize.io.allowed)
        io.nextDecision.foreach(_ := authorize.decision.get)
        Some(authorize)
    } else {
        require(!registerNextLineDecision)
        io.nextAllowed := false.B
        None
    }

    val origin = io.result.canonicalStoreOrigin.get
    val virtualAddress = io.result.originalVirtualAddress.get
    val ordinaryStore = request.write && !request.atomic && !request.virtualized &&
        !request.precheckedLoad && !request.uncached && io.result.checkPhysical
    val shape = request.size <= 3.U && AlignedMemoryDisjoint.aligned(virtualAddress, request.size) &&
        AlignedMemoryDisjoint.aligned(request.address, request.size) &&
        virtualAddress(11, 0) === request.address(11, 0) &&
        request.mask === AlignedMemoryDisjoint.lanes(request.address, request.size)
    // Preserve the original XLEN+1 whole interval and no-wrap requirement.
    val physicalStart = Cat(0.U(1.W), request.address)
    val bytes = MuxLookup(request.size, 8.U(65.W))(
        Seq(0.U -> 1.U(65.W), 1.U -> 2.U(65.W), 2.U -> 4.U(65.W)))
    val physicalEnd = physicalStart + bytes
    val wholeRam = physicalStart >= p.speculativeRamBase.U(65.W) &&
        physicalEnd <= (p.speculativeRamBase + p.speculativeRamBytes).U(65.W) && physicalEnd > physicalStart
    val fresh = io.authorization.stable && !io.authorization.changing && !io.authorization.flush &&
        origin.bits.epoch === io.authorization.epoch
    io.canonical.valid := origin.valid && ordinaryStore && shape && wholeRam && fresh &&
        !io.fault && !pmp.io.denied
    io.canonical.bits.origin := origin.bits
    io.canonical.bits.virtualAddress := virtualAddress
    io.canonical.bits.physicalAddress := request.address
    io.canonical.bits.size := request.size
    io.canonical.bits.mask := request.mask
}
