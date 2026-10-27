package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.bus.tilelink._
import soc.core.ooo._

/** Integration-only companion: real frontend, two owners/results, aligned PMP,
  * translation/ITLB/PTE bridge, request buffer, physical I-cache and packet FIFO.
  * Host TL and scalar-PTE ports are observation/service boundaries, not real MMIO.
  * No CPU or trap-selection claim follows from this supply fixture.
  */
class IdentityFetchHorizonSupplyGsim(enabled: Boolean = true) extends Module {
    private val transactionSlots = 2
    private val alignedSinglePage = true
    private val circularFetchPayload = true
    private val testRamBytes = BigInt(128 * 1024)
    private val config = FpgaNextConfig.Selected
    private val p = config.coreParams.copy(alignedFetchSinglePage = alignedSinglePage,
        circularFetchPayload = circularFetchPayload)
    private val tlp = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    require(p.renameWidth == 2 && p.frontendCacheSets == 16 && p.registeredFetchPacket)
    require(!p.alignedFetchPermissionStage && !p.fetchAddressBeforePmp && !p.fetchPreviousPacket)
    val io = IO(new Bundle {
        val enable = Input(Bool())
        val pause = Input(Bool())
        val budget = Input(UInt(2.W))
        val restart = Input(Bool())
        val restartPc = Input(UInt(64.W))
        val invalidate = Input(Bool())
        val flushTlb = Input(Bool())
        val satp = Input(UInt(64.W))
        val privilege = Input(UInt(2.W))
        val pmpCfg0 = Input(UInt(8.W))
        val pmpAddr0 = Input(UInt(54.W))
        val lane0 = Output(Valid(new RawFetchInstruction))
        val lane1 = Output(Valid(new RawFetchInstruction))
        val rawCount = Output(UInt(2.W))
        val capturedCount = Output(UInt(2.W))
        val consumedCount = Output(UInt(2.W))
        val occupancy = Output(UInt(3.W))
        val fetchPc = Output(UInt(64.W))
        val quiescent = Output(Bool())
        val virtualRequest = Output(Bool())
        val virtualResponse = Output(Bool())
        val virtualAddress = Output(UInt(64.W))
        val virtualValid = Output(Bool())
        val virtualReady = Output(Bool())
        val virtualMask = Output(UInt(2.W))
        val virtualReturnData = Output(UInt(64.W))
        val virtualReturnErrors = Output(UInt(2.W))
        val virtualReturnPages = Output(UInt(2.W))
        val physicalRequest = Output(Bool())
        val physicalResponse = Output(Bool())
        val physicalAddress = Output(UInt(64.W))
        val tlbHit = Output(Bool())
        val walkStart = Output(Bool())
        val cacheClass = Output(UInt(3.W))
        val aValid = Output(Bool())
        val aReady = Input(Bool())
        val aAddress = Output(UInt(64.W))
        val aSize = Output(UInt(3.W))
        val aSource = Output(UInt(3.W))
        val aMask = Output(UInt(8.W))
        val dValid = Input(Bool())
        val dReady = Output(Bool())
        val dData = Input(UInt(64.W))
        val dSize = Input(UInt(3.W))
        val dSource = Input(UInt(3.W))
        val dDenied = Input(Bool())
        val pteValid = Output(Bool())
        val pteReady = Input(Bool())
        val pteAddress = Output(UInt(64.W))
        val pteResponseValid = Input(Bool())
        val pteResponseReady = Output(Bool())
        val pteData = Input(UInt(64.W))
        val pteError = Input(Bool())
    })
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := io.pmpCfg0
    pmp.addr(0) := io.pmpAddr0
    PmpState.decodeRegions(pmp)
    val vm = WireDefault(0.U.asTypeOf(new VmCsrState))
    vm.satp := io.satp
    vm.dataPrivilege := io.privilege
    val virtualized = io.satp(63, 60) =/= 0.U && io.privilege =/= 3.U
    val frontend = Module(new SynchronousFetch(16, p.compressedInstructions, p.frontendCacheSets,
        p.renameWidth, stableFaultMetadata = p.stableFetchFaultMetadata, alignedFetchPmp = p.alignedFetchPmp,
        rawFetchPresence = p.rawFetchPresence, parallelFetchTagLookup = p.parallelFetchTagLookup,
        parallelAlignment = p.parallelFetchAlignment, registeredWindow = p.registeredFetchWindow,
        independentPayloadCapture = p.independentFetchPayloadCapture, fetchPreviousPacket = p.fetchPreviousPacket,
        transactionSlots = transactionSlots, fetchThirdPacketLookahead = enabled,
        sideEffectFreeFetchRanges = Seq(SideEffectFreeFetchRange(config.ramBase, testRamBytes))))
    val adapter = Module(new InstructionTranslationAdapter(p, transactionSlots = transactionSlots,
        withRequestContext = true))
    adapter.io.virtual <> frontend.io.memory
    adapter.io.vmState := vm
    adapter.io.privilege := io.privilege
    adapter.io.pmpState := pmp
    val requests = Module(new InstructionRequestBuffer(2, p.flowThroughFetchRequests, p.independentFetchCapture,
        withRequestContext = true))
    requests.io.upstream <> adapter.io.physical
    val cache = Module(new InstructionLineCache(tlp, ramBase = config.ramBase, ramBytes = testRamBytes,
        romBytes = 128 * 1024, lines = 8, packetWords = 2, prefetchEnabled = false,
        bankedData = config.bankedInstructionData, parallelFallbackAddresses = p.parallelFetchAddresses,
        tagConfig = config.tags, withRequestContext = true))
    cache.io.fetch <> requests.io.downstream
    cache.io.pmpState := pmp
    cache.io.privilege := io.privilege
    cache.io.invalidate := io.invalidate
    val tlb = Module(new SvTranslationService(3, entries = 8))
    val pte = Module(new SvPteDataBridge(4))
    tlb.io.client <> adapter.io.translation
    tlb.io.pmpState := pmp
    tlb.io.flush := io.flushTlb
    pte.io.walk <> tlb.io.memory
    pte.io.flush := io.flushTlb
    when(io.flushTlb) {
        assert(adapter.io.idle && tlb.io.idle && pte.io.idle, "fixture changed translation before drain")
    }

    val packet = Module(new RegisteredFetchPacket(2, p.compressedInstructions, BigInt("80000000", 16),
        p.parallelFetchValidation, p.fetchHintEntries, p.splitFetchCursor, p.bankedFetchHints, circularPayload = p.circularFetchPayload))
    val permission = Module(new FetchPacketPermission(16, 2, p.wordSpanPacketPmp,
        p.balancedPacketPmp, p.sharedFetchPmpRelations))
    permission.io.base := packet.io.fetchPc
    permission.io.state := pmp
    permission.io.privilege := io.privilege
    permission.io.virtualized := virtualized
    frontend.io.pc := packet.io.fetchPc
    frontend.io.enable := io.enable
    frontend.io.pause := io.pause || io.restart
    frontend.io.invalidate := io.invalidate
    frontend.io.pmpState := pmp
    frontend.io.privilege := io.privilege
    frontend.io.virtualized := virtualized
    packet.io.pause := io.pause || io.restart || !io.enable
    packet.io.flush.valid := io.restart
    packet.io.flush.bits := io.restartPc
    packet.io.invalidate := io.invalidate
    packet.io.expectedNext := 0.U.asTypeOf(packet.io.expectedNext)
    packet.io.validation.foreach(_ := 0.U.asTypeOf(packet.io.validation.get))
    packet.io.train := 0.U.asTypeOf(packet.io.train)
    for (lane <- 0 until 2) {
        permission.io.instructionLow(lane) := frontend.io.instructions(lane).bits(1, 0)
        packet.io.supply(lane).valid := frontend.io.instructions(lane).valid
        packet.io.supply(lane).bits := 0.U.asTypeOf(new RawFetchInstruction)
        packet.io.supply(lane).bits.instruction := frontend.io.instructions(lane).bits
        packet.io.supply(lane).bits.accessFault := frontend.io.instructionFaults(lane) || permission.io.denied(lane)
        packet.io.supply(lane).bits.pageFault := frontend.io.instructionPageFaults(lane)
        packet.io.supply(lane).bits.faultAddress := Mux(permission.io.denied(lane) &&
            !frontend.io.instructionFaults(lane) && !frontend.io.instructionPageFaults(lane),
            permission.io.faultAddresses(lane), frontend.io.instructionFaultAddresses(lane))
        packet.io.consume(lane) := io.enable && !io.pause && !io.restart && io.budget > lane.U &&
            packet.io.instructions(lane).valid
    }
    io.lane0 := packet.io.instructions(0)
    io.lane1 := packet.io.instructions(1)
    io.rawCount := PopCount(frontend.io.instructions.map(_.valid))
    io.capturedCount := PopCount(packet.io.captured)
    io.consumedCount := PopCount(packet.io.consume)
    io.occupancy := packet.io.occupancy
    io.fetchPc := packet.io.fetchPc
    io.quiescent := frontend.io.quiescent && adapter.io.idle && cache.io.idle && tlb.io.idle && pte.io.idle
    io.virtualRequest := frontend.io.memory.request.fire
    io.virtualResponse := frontend.io.memory.response.fire
    io.virtualAddress := frontend.io.memory.request.bits
    io.virtualValid := frontend.io.memory.request.valid
    io.virtualReady := frontend.io.memory.request.ready
    io.virtualMask := frontend.io.memory.requestMask
    io.virtualReturnData := frontend.io.memory.response.bits
    io.virtualReturnErrors := frontend.io.memory.responseError
    io.virtualReturnPages := frontend.io.memory.responsePageFault
    io.physicalRequest := adapter.io.physical.request.fire
    io.physicalResponse := adapter.io.physical.response.fire
    io.physicalAddress := adapter.io.physical.request.bits
    io.tlbHit := tlb.io.tlbHit
    io.walkStart := tlb.io.walkStart
    io.cacheClass := Cat(BoringUtils.bore(cache.perfAcceptedFallback),
        BoringUtils.bore(cache.perfAcceptedMiss), BoringUtils.bore(cache.perfAcceptedHit))

    io.aValid := cache.io.tl.a.valid
    cache.io.tl.a.ready := io.aReady
    io.aAddress := cache.io.tl.a.bits.address
    io.aSize := cache.io.tl.a.bits.size
    io.aSource := cache.io.tl.a.bits.source
    io.aMask := cache.io.tl.a.bits.mask
    cache.io.tl.d.valid := io.dValid
    cache.io.tl.d.bits := 0.U.asTypeOf(cache.io.tl.d.bits)
    cache.io.tl.d.bits.opcode := TLOpcode.AccessAckData
    cache.io.tl.d.bits.source := io.dSource
    cache.io.tl.d.bits.size := io.dSize
    cache.io.tl.d.bits.data := io.dData
    cache.io.tl.d.bits.denied := io.dDenied
    io.dReady := cache.io.tl.d.ready
    cache.io.tl.b.valid := false.B
    cache.io.tl.b.bits := 0.U.asTypeOf(cache.io.tl.b.bits)
    cache.io.tl.c.ready := false.B
    cache.io.tl.e.ready := false.B
    io.pteValid := pte.io.data.request.valid
    io.pteAddress := pte.io.data.request.bits.address
    pte.io.data.request.ready := io.pteReady
    pte.io.data.response.valid := io.pteResponseValid
    pte.io.data.response.bits := 0.U.asTypeOf(new DataResponse)
    pte.io.data.response.bits.data := io.pteData
    pte.io.data.response.bits.error := io.pteError
    io.pteResponseReady := pte.io.data.response.ready
}

object IdentityFetchHorizonSupplyGsimMain extends App {
    require(args.length == 2, "output-directory enabled")
    ChiselStage.emitCHIRRTLFile(new IdentityFetchHorizonSupplyGsim(args(1).toBoolean), Array("--target-dir", args.head))
}
