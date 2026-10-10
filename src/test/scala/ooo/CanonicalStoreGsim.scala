package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Dev-only fixtures. Production profiles remain unchanged. Expected permissions, byte intervals,
  * owner generations and response data are computed independently in canonical_store*.cpp.
  */
object CanonicalStoreFixture {
    def params(entries: Int = 2): OooParams = VirtualLoadPrecheckFixture.params(true).copy(
        canonicalVirtualStoreOverlap = true,
        bufferedRamStores = true,
        registeredMemoryRequests = true,
        registeredTranslationHeads = true,
        memoryEntries = entries,
        tagBits = 8)
}

class CanonicalStoreTrackerGsim extends Module {
    val p = CanonicalStoreFixture.params()
    val io = IO(new Bundle {
        val start = Input(Valid(new CanonicalStoreDescriptor(p)))
        val checked = Input(Valid(new CanonicalStoreCertificate(p)))
        val ownerLive = Input(Bool())
        val invalidate = Input(Bool())
        val stable = Input(Bool())
        val epoch = Input(UInt(32.W))
        val tracked = Output(Bool())
        val owner = Output(new RobToken(p))
        val certificate = Output(Valid(new CanonicalStoreCertificate(p)))
        // This is the production byte-disjoint helper, exercised independently of certificate contents.
        val loadAddress = Input(UInt(64.W))
        val loadSize = Input(UInt(2.W))
        val storeAddress = Input(UInt(64.W))
        val storeSize = Input(UInt(2.W))
        val disjoint = Output(Bool())
    })
    val tracker = Module(new CanonicalStoreTracker(p))
    tracker.io.start := io.start
    tracker.io.checked := io.checked
    tracker.io.ownerLive := io.ownerLive
    tracker.io.invalidate := io.invalidate
    tracker.io.stable := io.stable
    tracker.io.epoch := io.epoch
    io.tracked := tracker.io.tracked
    io.owner := tracker.io.owner
    io.certificate := tracker.io.certificate
    io.disjoint := AlignedMemoryDisjoint(io.loadAddress, io.loadSize, io.storeAddress, io.storeSize)
}

/** Real write translation, page walk, physical PMP and checked-queue certificate producer. */
class CanonicalStoreAdapterGsim extends Module {
    val p = CanonicalStoreFixture.params()
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val physical = new DataPort
        val pte = new SvPteReadPort
        val context = Input(new VmCsrState)
        val pmpCfg = Input(UInt(8.W))
        val pmpAddress = Input(UInt(54.W))
        val flush = Input(Bool())
        val origin = Input(Valid(new CanonicalStoreOrigin(p)))
        val certificate = Output(Valid(new CanonicalStoreCertificate(p)))
        val epoch = Output(UInt(32.W))
        val stable = Output(Bool())
        val translationHit = Output(Bool())
        val translationWalk = Output(Bool())
        val idle = Output(Bool())
    })
    val adapter = Module(new DataTranslationAdapter(p, registerCheckedRequests = true))
    val translation = Module(new SvTranslationService(3, 8, 16, loadPeek = true))
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := io.pmpCfg
    pmp.addr(0) := io.pmpAddress
    PmpState.decodeRegions(pmp)
    adapter.io.vmState := io.context
    adapter.io.pmpState := pmp
    translation.io.pmpState := pmp
    adapter.io.virtual <> io.upstream
    io.physical <> adapter.io.physical
    translation.io.client <> adapter.io.translation
    io.pte <> translation.io.memory
    translation.io.flush := io.flush
    adapter.io.canonicalStoreOrigin.get := io.origin
    io.certificate := adapter.io.canonicalStoreCertificate.get
    adapter.io.precheckFlush.get := io.flush
    adapter.io.loadPrecheck.get.request.valid := false.B
    adapter.io.loadPrecheck.get.request.bits := 0.U.asTypeOf(adapter.io.loadPrecheck.get.request.bits)
    translation.io.loadPeek.get <> adapter.io.translationPeek.get
    io.epoch := adapter.io.loadPrecheck.get.epoch
    io.stable := adapter.io.loadPrecheck.get.stable
    io.translationHit := translation.io.tlbHit
    io.translationWalk := translation.io.walkStart
    io.idle := adapter.io.idle && translation.io.idle
}

/** Exact-slot serial-owner exception without a backend oracle or synthetic certificate generator.
  * The driver supplies the already registered owner authorization and independently records all fires.
  */
class CanonicalStoreLsuGsim(entries: Int = 2) extends Module {
    val p = CanonicalStoreFixture.params(entries)
    val io = IO(new Bundle {
        val startValid = Input(Bool())
        val startReady = Output(Bool())
        val token = Input(new RobToken(p))
        val address = Input(UInt(64.W))
        val physicalAddress = Input(UInt(64.W))
        val data = Input(UInt(64.W))
        val size = Input(UInt(2.W))
        val store = Input(Bool())
        val atomic = Input(Bool())
        val virtualized = Input(Bool())
        val prechecked = Input(Bool())
        val forwarded = Input(Bool())
        val parallel = Input(Bool())
        val originValid = Input(Bool())
        val epoch = Input(UInt(32.W))
        val relaxOwner = Input(Valid(new RobToken(p)))
        val cancelOwner = Input(Valid(new RobToken(p)))
        val memory = new DataPort
        val origin = Output(Valid(new CanonicalStoreOrigin(p)))
        val requestOwner = Output(Valid(new RobToken(p)))
        val complete = Decoupled(new BackendCompletion(p))
        val liveMask = Output(UInt(entries.W))
        val busy = Output(Bool())
        val discarded = Output(Bool())
    })
    val lsu = Module(new ParallelLoadStoreUnit(p))
    lsu.io.start.valid := io.startValid
    lsu.io.start.bits := 0.U.asTypeOf(new MemoryOperation(p))
    lsu.io.start.bits.token := io.token
    lsu.io.start.bits.pc := "h1000".U
    lsu.io.start.bits.address := io.address
    lsu.io.start.bits.physicalAddress := io.physicalAddress
    lsu.io.start.bits.data := io.data
    lsu.io.start.bits.size := io.size
    lsu.io.start.bits.unsigned := true.B
    lsu.io.start.bits.store := io.store
    lsu.io.start.bits.atomic := io.atomic
    lsu.io.start.bits.virtualized := io.virtualized
    lsu.io.start.bits.precheckedLoad := io.prechecked
    lsu.io.start.bits.forward.valid := io.forwarded
    lsu.io.start.bits.forward.bits := io.data
    lsu.io.start.bits.translationEpoch := io.epoch
    lsu.io.start.bits.canonicalStoreEpoch.get.valid := io.originValid
    lsu.io.start.bits.canonicalStoreEpoch.get.bits := io.epoch
    lsu.io.issueDestination.foreach(_ := 0.U.asTypeOf(Valid(UInt(p.physBits.W))))
    lsu.io.parallel := io.parallel
    lsu.io.relaxStoreOwner.get := io.relaxOwner
    for (i <- 0 until entries) {
        lsu.io.cancel(i) := io.cancelOwner.valid && lsu.io.live(i) &&
            lsu.io.owner(i).asUInt === io.cancelOwner.bits.asUInt
    }
    lsu.io.fastStoreRetire := false.B
    lsu.io.fastLoadRetire := false.B
    io.startReady := lsu.io.start.ready
    io.memory <> lsu.io.memory
    io.origin := lsu.io.canonicalStoreOrigin.get
    io.requestOwner := lsu.io.requestOwner
    io.complete <> lsu.io.complete
    io.liveMask := lsu.io.live.asUInt
    io.busy := lsu.io.busy
    io.discarded := lsu.io.discarded
}

object CanonicalStoreTrackerGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new CanonicalStoreTrackerGsim, Array("--target-dir", args.head))
}
object CanonicalStoreAdapterGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new CanonicalStoreAdapterGsim, Array("--target-dir", args.head))
}
object CanonicalStoreLsuGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new CanonicalStoreLsuGsim(args.lift(1).map(_.toInt).getOrElse(2)),
        Array("--target-dir", args.head))
}
