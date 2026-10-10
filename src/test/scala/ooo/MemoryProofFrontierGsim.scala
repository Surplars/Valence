package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Test-only composition. Permission expectations are authored from raw host page tables/PMP. */
object MemoryProofFrontierFixture {
    def params(enabled: Boolean = true): OooParams = BoardSocConfig.timingParams("staged-load-issue").copy(
        robEntries = 64, physicalRegs = 64, memoryEntries = 4, tagBits = 64,
        machineSystem = true, pmpEntries = 16, virtualMemoryLevels = 3,
        virtualRamLoadPrecheck = true, canonicalVirtualStoreOverlap = true,
        bufferedRamStores = true, registeredMemoryAddress = true, registeredMemoryRequests = true,
        parallelMemoryPreparation = true, parallelMemoryPayload = true, compactMemoryOperandSelect = true,
        registeredTranslationHeads = true, registeredTranslatedResponses = true, registeredFabricBoundary = true,
        registeredLoadReplay = true, loadOrderOlderRetire = true,
        precheckedDataRequestFlow = false, fastBufferedStoreRetire = false, fastHeadLoadRetire = false,
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 65536,
        memoryProofFrontier = enabled, memoryProofRows = 16, memoryProofCacheSets = 256)

    def pmp(cfg: UInt, address: UInt): PmpState = {
        val state = WireDefault(0.U.asTypeOf(new PmpState))
        state.cfg(0) := cfg
        state.addr(0) := address
        PmpState.decodeRegions(state)
        state
    }
}

/** Real bank + real access-keyed Sv39 service + physical preparation PMP.
  * Warmth can only be installed by ordinary DataPort requests and returned PTE bytes.
  * The test-only owner table stores independent host allocations; it is not a proof source.
  */
class MemoryProofFrontierBankGsim extends Module {
    val p = MemoryProofFrontierFixture.params()
    val io = IO(new Bundle {
        val allocate = Input(Valid(new MemoryProofQuery(p)))
        val head = Input(UInt(p.robBits.W))
        val pending = Input(UInt(64.W))
        val memoryLive = Input(UInt(64.W))
        val ordinary = Input(UInt(64.W))
        val stores = Input(UInt(64.W))
        val systems = Input(UInt(64.W))
        val canonicalLoads = Input(UInt(64.W))
        val canonicalStores = Input(UInt(64.W))
        val checkedStore = Input(Valid(new CanonicalStoreCertificate(p)))
        val clearOwners = Input(UInt(64.W))
        val pause = Input(Bool())
        val cancelQueries = Input(Bool())
        val queryEligible = Input(UInt(64.W))
        val selected = Input(Valid(new RobToken(p)))
        val consume = Input(Valid(new RobToken(p)))
        val frontierAccepted = Input(Bool())
        val oldLine = Input(Valid(new MemoryProofLine(p)))
        val warm = Flipped(new DataPort)
        val physical = new DataPort
        val pte = new SvPteReadPort
        val context = Input(new VmCsrState)
        val pmpCfg = Input(UInt(8.W))
        val pmpAddress = Input(UInt(54.W))
        val flush = Input(Bool())
        val queryOwner = Output(Valid(UInt(p.robBits.W)))
        val query = Output(Valid(new VirtualLoadPrecheckRequest))
        val queryHit = Output(Valid(new VirtualLoadPrecheckResponse))
        val selectedProof = Output(Valid(new MemoryAddressProof(p)))
        val selectedBound = Output(Bool())
        val frontier = Output(Valid(new MemoryAddressProof(p)))
        val pendingProof = Output(UInt(64.W))
        val reservedCount = Output(UInt(5.W))
        val allowedCount = Output(UInt(5.W))
        val boundCount = Output(UInt(5.W))
        val epoch = Output(UInt(32.W))
        val stable = Output(Bool())
        val translationWalk = Output(Bool())
        val idle = Output(Bool())
    })
    val owners = Reg(Vec(64, new MemoryProofQuery(p)))
    when(io.allocate.valid) { owners(io.allocate.bits.token.index) := io.allocate.bits }
    val bank = Module(new MemoryProofFrontier(p))
    val adapter = Module(new DataTranslationAdapter(p, registerCheckedRequests = true))
    val translation = Module(new SvTranslationService(3, 16, 16, loadPeek = true))
    val pmp = MemoryProofFrontierFixture.pmp(io.pmpCfg, io.pmpAddress)
    bank.io.head := io.head
    bank.io.pending := io.pending
    bank.io.memoryLive := io.memoryLive
    bank.io.ordinary := io.ordinary
    bank.io.stores := io.stores
    bank.io.systems := io.systems
    bank.io.canonicalLoads := io.canonicalLoads
    bank.io.canonicalStores := io.canonicalStores
    bank.io.checkedStore := io.checkedStore
    bank.io.clearOwners := io.clearOwners
    bank.io.pause := io.pause
    bank.io.flushQueries := io.cancelQueries || io.flush
    bank.io.queryEligible := io.queryEligible
    bank.io.query := owners(bank.io.queryOwner.bits)
    bank.io.resultToken := owners(bank.io.resultIndex).token
    bank.io.pmpState := pmp
    bank.io.privilege := io.context.dataPrivilege
    bank.io.selected := io.selected
    bank.io.consume := io.consume
    bank.io.frontierAccepted := io.frontierAccepted
    bank.io.liveLines := 0.U.asTypeOf(bank.io.liveLines)
    bank.io.liveLines(0) := io.oldLine
    bank.io.precheck <> adapter.io.loadPrecheck.get
    adapter.io.virtual <> io.warm
    adapter.io.canonicalStoreOrigin.get := 0.U.asTypeOf(adapter.io.canonicalStoreOrigin.get)
    adapter.io.frozenStoreProof.get := 0.U.asTypeOf(adapter.io.frozenStoreProof.get)
    adapter.io.vmState := io.context
    adapter.io.pmpState := pmp
    adapter.io.precheckFlush.get := io.flush
    translation.io.client <> adapter.io.translation
    translation.io.loadPeek.get <> adapter.io.translationPeek.get
    translation.io.pmpState := pmp
    translation.io.flush := io.flush
    io.physical <> adapter.io.physical
    io.pte <> translation.io.memory
    io.queryOwner := bank.io.queryOwner
    io.query := bank.io.precheck.request
    io.queryHit := bank.io.precheck.response
    io.selectedProof := bank.io.selectedProof
    io.selectedBound := bank.io.selectedBound
    io.frontier := bank.io.frontier
    io.pendingProof := bank.io.pendingProof
    io.reservedCount := bank.io.reservedCount
    io.allowedCount := bank.io.allowedCount
    io.boundCount := bank.io.boundCount
    io.epoch := adapter.io.loadPrecheck.get.epoch
    io.stable := adapter.io.loadPrecheck.get.stable
    io.translationWalk := translation.io.walkStart
    io.idle := adapter.io.idle && translation.io.idle
}

/** Real StoreBuffer -> registered adapter -> real Sv39 service -> physical boundary.
  * OFF and ON share IO; the host independently verifies origin/token and every accepted byte.
  */
class MemoryProofFrontierTransportGsim(enabled: Boolean) extends Module {
    val p = MemoryProofFrontierFixture.params(enabled)
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
    val adapter = Module(new DataTranslationAdapter(p, registerCheckedRequests = true))
    val translation = Module(new SvTranslationService(3, 16, 16, loadPeek = true))
    val pmp = MemoryProofFrontierFixture.pmp(io.pmpCfg, io.pmpAddress)
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

object MemoryProofFrontierBankGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new MemoryProofFrontierBankGsim, Array("--target-dir", args.head))
}
object MemoryProofFrontierTransportGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new MemoryProofFrontierTransportGsim(args.lift(1).contains("1")),
        Array("--target-dir", args.head))
}
