package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

/** Independent off/on fixtures: both sides enable virtual certificates; only queue flow changes.
  * These wrappers expose events, never expected permission, mapping, ordering or retirement verdicts.
  */
object PrecheckedQueueFlowFixture {
    def params(enabled: Boolean): OooParams = BoardSocConfig.timingParams("staged-load-issue").copy(
        machineSystem = true, pmpEntries = 16, virtualMemoryLevels = 3,
        virtualRamLoadPrecheck = true, precheckedDataRequestFlow = enabled,
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 65536)
}

class PrecheckedQueueFlowGsim(enabled: Boolean, prefetch: Boolean = false) extends Module {
    val p = PrecheckedQueueFlowFixture.params(enabled).copy(dataNextLinePrefetch = prefetch)
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val physical = new DataPort
        val pte = new SvPteReadPort
        val context = Input(new VmCsrState)
        val pmpCfg = Input(UInt(8.W))
        val pmpAddress = Input(UInt(54.W))
        val flush = Input(Bool())
        val queryValid = Input(Bool())
        val queryAddress = Input(UInt(64.W))
        val querySize = Input(UInt(2.W))
        val queryHit = Output(Bool())
        val queryPhysical = Output(UInt(64.W))
        val queryPbmt = Output(UInt(2.W))
        val queryEpoch = Output(UInt(32.W))
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
    io.queryHit := false.B
    io.queryPhysical := 0.U
    io.queryPbmt := 0.U
    io.queryEpoch := 0.U
    io.epoch := 0.U
    io.stable := false.B
    if (true) {
        adapter.io.loadPrecheck.get.request.valid := io.queryValid
        adapter.io.loadPrecheck.get.request.bits.address := io.queryAddress
        adapter.io.loadPrecheck.get.request.bits.size := io.querySize
        adapter.io.loadPrecheck.get.request.bits.write := false.B
        adapter.io.precheckFlush.get := io.flush
        translation.io.loadPeek.get <> adapter.io.translationPeek.get
        io.queryHit := adapter.io.loadPrecheck.get.response.valid
        io.queryPhysical := adapter.io.loadPrecheck.get.response.bits.physicalAddress
        io.queryPbmt := adapter.io.loadPrecheck.get.response.bits.pbmt
        io.queryEpoch := adapter.io.loadPrecheck.get.response.bits.epoch
        io.epoch := adapter.io.loadPrecheck.get.epoch
        io.stable := adapter.io.loadPrecheck.get.stable
    }
    io.translationHit := translation.io.tlbHit
    io.translationWalk := translation.io.walkStart
    io.idle := adapter.io.idle && translation.io.idle
}

class PrecheckedQueueFlowBackendGsim(enabled: Boolean) extends Module {
    val p = PrecheckedQueueFlowFixture.params(enabled)
    val io = IO(new Bundle {
        val allocate0 = Input(Valid(new IntegerRequest))
        val allocate1 = Input(Valid(new IntegerRequest))
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
    })
    val backend = Module(new IntegerBackend(p))
    val adapter = Module(new DataTranslationAdapter(p, registerCheckedRequests = true))
    val translation = Module(new SvTranslationService(3, 8, 16, loadPeek = true))
    backend.io.rawDestinations.foreach { ports =>
        ports(0) := io.allocate0.bits.rename.rd
        ports(1) := io.allocate1.bits.rename.rd
    }
    backend.io.rawRequests.foreach { ports =>
        ports(0) := io.allocate0.bits.rename
        ports(1) := io.allocate1.bits.rename
    }
    backend.io.fetchFaultMask.foreach(_ := 0.U)
    backend.io.externalPrefetchBusy.foreach(_ := false.B)
    backend.io.allocate(0) := io.allocate0
    backend.io.allocate(1) := io.allocate1
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
    io.physical <> adapter.io.physical
    io.pte <> translation.io.memory
    io.queryValid := false.B
    io.queryHit := false.B
    io.queryAddress := 0.U
    io.queryPhysical := 0.U
    io.epoch := 0.U
    if (true) {
        backend.io.loadPrecheck.get <> adapter.io.loadPrecheck.get
        adapter.io.precheckFlush.get := flush
        translation.io.loadPeek.get <> adapter.io.translationPeek.get
        io.queryValid := backend.io.loadPrecheck.get.request.valid
        io.queryHit := backend.io.loadPrecheck.get.response.valid
        io.queryAddress := backend.io.loadPrecheck.get.request.bits.address
        io.queryPhysical := backend.io.loadPrecheck.get.response.bits.physicalAddress
        io.epoch := adapter.io.loadPrecheck.get.epoch
    }
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

object PrecheckedQueueFlowGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new PrecheckedQueueFlowGsim(args.lift(1).contains("1"), args.lift(2).contains("prefetch")),
        Array("--target-dir", args.head))
}

object PrecheckedQueueFlowBackendGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new PrecheckedQueueFlowBackendGsim(args.lift(1).contains("1")),
        Array("--target-dir", args.head))
}

