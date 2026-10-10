package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.core.ooo._

/** Focused real backend/service/adapter/cache assembly. The host supplies an
  * independent TileLink manager, raw PTEs and exact architectural byte oracle.
  * No production defaults, original guest or original backend negatives change.
  */
class MemoryProofFrontierBackendGsim(frontierEnabled: Boolean) extends Module {
    private val overlap = true
    private val memoryEntries = 4
    private val enabled = true
    val p = MemoryProofFrontierFixture.params(frontierEnabled)
    private val concurrency = CoherentCacheConcurrency(readMshrs = 2, responseEntries = 2, writebackEntries = 2)
    private val tlParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = concurrency.sinkBits)
    require(p.memoryProofCacheSets == 512 / 2)
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
        val tl = new TLBundle(tlParams)
        val cacheFlush = Input(Bool())
        val cacheFlushDone = Output(Bool())
        val cacheRequest = Output(Valid(new DataRequest))
        val cacheRequestFire = Output(Bool())
        val cacheResponse = Output(Valid(new DataResponse))
        val cacheResponseFire = Output(Bool())
        val cacheMiss = Output(Bool())
        val demandMiss = Output(Bool())
        val demandMissAddress = Output(UInt(64.W))
        val mshrOccupancy = Output(UInt(3.W))
        val queryWrite = Output(Bool())
        val queryToken = Output(Valid(new RobToken(p)))
        val insertedProof = Output(Valid(new MemoryAddressProof(p)))
        val boundCount = Output(UInt(5.W))
        val reservedCount = Output(UInt(5.W))
        val frozenRequest = Output(Valid(new FrozenStoreProof))
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
    val backend = Module(new IntegerBackend(p))
    val adapter = Module(new DataTranslationAdapter(p, registerCheckedRequests = true))
    val translation = Module(new SvTranslationService(3, 16, 16, loadPeek = enabled))
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
    io.canonicalOrigin := 0.U.asTypeOf(io.canonicalOrigin)
    io.canonicalChecked := 0.U.asTypeOf(io.canonicalChecked)
    if (overlap) {
        adapter.io.canonicalStoreOrigin.get := backend.io.canonicalStore.get.requestOrigin
        backend.io.canonicalStore.get.checked := adapter.io.canonicalStoreCertificate.get
        io.canonicalOrigin := backend.io.canonicalStore.get.requestOrigin
        io.canonicalChecked := adapter.io.canonicalStoreCertificate.get
    }
    adapter.io.frozenStoreProof.foreach(_ := backend.io.canonicalStore.get.requestFrozenProof.get)
    io.frozenRequest := backend.io.canonicalStore.get.requestFrozenProof.getOrElse(0.U.asTypeOf(io.frozenRequest))
    val cache = Module(new NonBlockingCoherentLineCache(base = p.speculativeRamBase,
        bytes = p.speculativeRamBytes, lines = 512, ways = 2, params = tlParams, concurrency = concurrency))
    cache.io.upstream <> adapter.io.physical
    io.physical <> cache.io.downstream
    io.tl <> cache.io.tl
    cache.io.flushRequest := io.cacheFlush
    io.cacheFlushDone := cache.io.flushDone
    io.cacheRequest.valid := adapter.io.physical.request.valid
    io.cacheRequest.bits := adapter.io.physical.request.bits
    io.cacheRequestFire := adapter.io.physical.request.fire
    io.cacheResponse.valid := adapter.io.physical.response.valid
    io.cacheResponse.bits := adapter.io.physical.response.bits
    io.cacheResponseFire := adapter.io.physical.response.fire
    io.cacheMiss := cache.io.miss
    io.demandMiss := BoringUtils.bore(cache.observationStorePrefetch.demandAlloc)
    io.demandMissAddress := BoringUtils.bore(cache.observationStorePrefetch.demandAllocAddress)
    io.mshrOccupancy := BoringUtils.bore(cache.mshrOccupancy)
    io.queryWrite := backend.io.loadPrecheck.get.request.bits.write
    io.queryToken := 0.U.asTypeOf(io.queryToken)
    io.insertedProof := 0.U.asTypeOf(io.insertedProof)
    io.boundCount := 0.U
    io.reservedCount := 0.U
    backend.proofFrontier.foreach { f =>
        io.queryToken.valid := BoringUtils.bore(f.io.precheck.request.valid)
        io.queryToken.bits := BoringUtils.bore(f.addressProof.token)
        val removed = BoringUtils.bore(f.removedRows)
        val resultRow = BoringUtils.bore(f.resultRow)
        io.insertedProof.valid := BoringUtils.bore(f.positiveResult) && !removed(resultRow)
        io.insertedProof.bits := BoringUtils.bore(f.resultProof)
        io.boundCount := BoringUtils.bore(f.io.boundCount)
        io.reservedCount := BoringUtils.bore(f.io.reservedCount)
    }
    io.pte <> translation.io.memory
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
        io.queryPhysical := backend.io.loadPrecheck.get.response.bits.physicalAddress
        io.epoch := adapter.io.loadPrecheck.get.epoch
    }
    io.serialStoreOwner.valid := BoringUtils.bore(backend.memoryProtected)
    io.serialStoreOwner.bits := BoringUtils.bore(backend.memoryOwner)
    io.serialStoreSlotLive := (0 until memoryEntries).map { i =>
        BoringUtils.bore(backend.lsu.io.live(i)) && !BoringUtils.bore(backend.lsu.parallel(i)) &&
            BoringUtils.bore(backend.lsu.io.owner(i)).asUInt === io.serialStoreOwner.bits.asUInt
    }.reduce(_ || _)
    io.lsuLive := VecInit((0 until memoryEntries).map(i => BoringUtils.bore(backend.lsu.io.live(i)))).asUInt
    io.physicalResponseFire := adapter.io.physical.response.fire
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

object MemoryProofFrontierBackendGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)))
    ChiselStage.emitCHIRRTLFile(new MemoryProofFrontierBackendGsim(args(1) == "1"),
        Array("--target-dir", args.head))
}
