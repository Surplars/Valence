package ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._
import soc.ip.bus.RegisterPort
import soc.ip.debug.DebugDmiPort

/** Explicit services outside the native CPU/fabric clock domain. */
class MatchingBoardServices extends Bundle {
    val uart = new RegisterPort
    val uartRx = Output(Bool())
    val uartTx = Input(Bool())
    val uartIrq = Input(Bool())
    val uartQuiesce = Input(Bool())
    val uartIsolate = Input(Bool())
    val uartIdle = Input(Bool())
    val uartWake = Output(Bool())
    val uartDrained = Output(Bool())
    val cmu = new RegisterPort
    val cmuIrq = Input(Bool())
    val gmac = new MatchingGmacService
    val jtagDmi = Flipped(new DebugDmiPort(7))
    val jtagLinkUp = Input(Bool())
    val peripheralReset = Output(Bool())
    val memoryDmaActive = Output(Bool())
    val packetDmaActive = Output(Bool())
    val packetDmaIrq = Output(Bool())
    val gmacMmioValid = Output(Bool())
    val cpuMemoryFire = Output(Bool())
    val memoryBusy = Output(Bool())
    val packetRequestFire = Output(Bool())
    val packetRequestValid = Output(Bool())
    val packetRequestReady = Output(Bool())
    val packetRequestWrite = Output(Bool())
    val packetRequestAddress = Output(UInt(64.W))
    val packetRequestData = Output(UInt(64.W))
    val packetRequestMask = Output(UInt(8.W))
    val packetRequestSize = Output(UInt(3.W))
    val packetResponseFire = Output(Bool())
    val packetResponseValid = Output(Bool())
    val packetResponseReady = Output(Bool())
    val packetResponseData = Output(UInt(64.W))
    val packetResponseError = Output(Bool())
    val scalarDmaFire = Output(Bool())
    val lineDmaFire = Output(Bool())
    val lineRequestValid = Output(Bool())
    val lineRequestReady = Output(Bool())
    val lineRequestTag = Output(UInt(2.W))
    val lineRequestAddress = Output(UInt(64.W))
    val lineRequestWrite = Output(Bool())
    val lineRequestData = Output(new PostedBoardWords)
    val lineResponseFire = Output(Bool())
    val lineResponseValid = Output(Bool())
    val lineResponseReady = Output(Bool())
    val lineResponseTag = Output(UInt(2.W))
    val lineResponseError = Output(Bool())
    val lineResponseData = Output(new PostedBoardWords)
    val probeFire = Output(Bool())
    val probeReplyDataFire = Output(Bool())
    val jtagRequestFire = Output(Bool())
    val jtagRequestValid = Output(Bool())
    val jtagRequestReady = Output(Bool())
    val jtagRequestAddress = Output(UInt(64.W))
    val jtagRequestWrite = Output(Bool())
    val jtagRequestData = Output(UInt(64.W))
    val jtagRequestSize = Output(UInt(3.W))
    val jtagRequestMask = Output(UInt(8.W))
    val jtagResponseFire = Output(Bool())
    val jtagResponseValid = Output(Bool())
    val jtagResponseReady = Output(Bool())
    val jtagResponseData = Output(UInt(64.W))
    val jtagResponseError = Output(Bool())
}

/** Test-only native managed-board CPU/fabric envelope. It intentionally has
  * BoardSocTop's simulation-facing IO shape and a real `platform` member, so
  * existing passive CPU probes and independent C++ oracles stay unchanged.
  * Only native ROM storage and the documented physical/CDC services differ.
  */
class MatchingManagedBoard(config: FpgaNextConfig, jtagRamDownload: Boolean = true) extends Module {
    require(config.experimentalTriSpeedEthernet && jtagRamDownload,
        "this final assembly requires tri-speed GMAC and the real JTAG RAM loader")
    private val p = config.coreParams
    // This fixture deliberately accepts only the reviewed full board geometry.
    require(p.robEntries == 16 && p.physicalRegs == 48 && config.lsuEntries == 4)
    require(config.dataTranslationEntries == 16 && config.dmaLineEntries == 4 && config.dmaLineTransfers)
    require(config.dataCacheLines == 512 && config.instructionCacheLines == 512 && config.cacheWays == 2)
    require(config.ddr.maxOutstanding == 4 && config.ddr.maxOutstandingWrites == 2)
    require(p.registeredFabricBoundary, "the reviewed profile selects registered translated responses")

    // Exact mapping of BoardSocTop.platform for config.managedBoard(...).
    // The only intentional MachinePlatform constructor differences are:
    // programmable=true and vivadoMemories=false (ROM loading/model boundary).
    val platform = Module(new MachinePlatform(
        p,
        romWords = BoardSocConfig.romWords,
        romFiles = Seq.empty,
        programmable = true,
        tileLinkMemory = true,
        tileLinkFetch = true,
        ramBytes = config.ddrBytes,
        instructionLineCacheLines = config.instructionCacheLines,
        translationService = true,
        translationLevels = 3,
        coreDataTranslation = true,
        coreInstructionTranslation = true,
        coherentLineCache = true,
        coherentLineCacheLines = config.dataCacheLines,
        pteCacheEntries = 4,
        dataTranslationEntries = config.dataTranslationEntries,
        dataTlbWriteReadReuse = config.dataTlbWriteReadReuse,
        translationHitFlow = config.translationHitFlow,
        bufferCoherentResponses = true,
        vivadoMemories = false,
        ramReadLatency = BoardSocConfig.ramReadLatency,
        uartClockHz = config.cpuHz,
        uartFastDivisorOne = true,
        externalDdr = true,
        registerCoherentResponses = config.timingProfile == "registered-response",
        uartReferenceClockHz = config.uartBaud * 16,
        coherentLineCacheWays = config.cacheWays,
        instructionLineCachePrefetch = config.instructionPrefetch,
        registerPhysicalResponseOwners = true,
        stagedMemoryFabric = BoardSocConfig.usesStagedMemoryFabric(config.timingProfile, p),
        // The native expression is a list of old profiles OR this true flag.
        bufferTranslatedResponses = p.registeredFabricBoundary,
        peripheralClockHz = config.uartHz,
        ethernetControl = true,
        ethernetDma = true,
        clockManagement = true,
        externalUart = true,
        ddrBridge = config.ddr,
        cacheConcurrency = config.cache,
        tagConfig = config.tags,
        networkDmaConfig = config.network,
        bankedInstructionData = config.bankedInstructionData,
        jtagRamDownload = jtagRamDownload,
        dmaLineTransfers = config.dmaLineTransfers,
        dmaLineYieldCycles = config.dmaLineYieldCycles,
        dmaLineEntries = config.dmaLineEntries,
        lineTransferDispatchFlow = config.lineTransferDispatchFlow
    ))

    // Checks inspect the constructed instances, not just an input JSON manifest.
    require(platform.core.core.core.p == config.coreParams)
    require(platform.core.core.core.backend.lsu.slots.size == config.lsuEntries)
    require(platform.packetDma.nonEmpty && platform.dmaArbiter.nonEmpty)
    require(platform.packetDma.get.slotOwned.size == config.network.postedRxSlots)
    require(platform.packetDma.get.txQueue.nonEmpty)
    require(platform.jtagLoader.nonEmpty == jtagRamDownload)
    require(platform.debugDmaArbiter.nonEmpty == jtagRamDownload)
    require(platform.platformRouter.get.io.registers.size == (if (jtagRamDownload) 7 else 6))
    require(platform.dma.io.line.nonEmpty && platform.shared.io.dmaLine.nonEmpty)
    require(platform.uart.isEmpty && platform.uartCdc.isEmpty,
        "no local UART clock/reset logic may survive this boundary")

    val io = IO(new Bundle {
        val uartRx = Input(Bool())
        val uartTx = Output(Bool())
        val program = Some(Input(chiselTypeOf(platform.io.program.get)))
        val ramProgram = None: Option[Data]
        val ddrReady = Some(Input(Bool()))
        val ddrAxi = Some(new soc.ip.axi.Axi4MemoryPort(32, config.ddr.axiIdWidth))
        val commit = Some(Output(chiselTypeOf(platform.io.commit)))
        val trap = Some(Output(chiselTypeOf(platform.io.trap)))
        val fetchPc = Some(Output(UInt(64.W)))
        val fetchWait = Some(Output(Bool()))
        val cacheProfile = Some(Output(new CoherentCacheProfile))
        val headProfile = Some(Output(new HeadProfile))
    })
    val service = IO(new MatchingBoardServices)
    platform.io.program.get := io.program.get
    platform.io.ddrReady.get := io.ddrReady.get
    io.ddrAxi.get <> platform.io.ddrAxi.get
    // This native input has no consumer because externalUart=true. It is
    // deliberately inactive, never an alias for a real peripheral clock.
    platform.io.peripheralClock.get := false.B.asClock
    platform.io.timerTick := true.B
    platform.io.commitEnable := true.B
    platform.io.inspectRegister := 0.U
    platform.io.translationFlush.get := false.B
    platform.io.uartRx := io.uartRx
    platform.io.externalUartIrq.get := service.uartIrq
    platform.io.jtagDmi.get <> service.jtagDmi
    platform.io.jtagLinkUp.get := service.jtagLinkUp
    service.uartRx := io.uartRx
    io.uartTx := service.uartTx
    service.cmu <> platform.io.clockManagementRegisters.get

    // Native bank's common cold reset is reset || !ddrReady, not program.hold.
    // Preserve the three CPU release edges while explicitly modeling assertion
    // synchronously; independent asynchronous-reset qualification is excluded.
    val commonColdReset = reset.asBool || !io.ddrReady.get
    val cpuPeripheralRelease = withReset(commonColdReset) {
        val release = RegInit(7.U(3.W))
        release := Cat(release(1, 0), false.B)
        release(2)
    }
    val cpuPeripheralReset = commonColdReset || cpuPeripheralRelease
    service.peripheralReset := cpuPeripheralReset
    val gmac = withReset(cpuPeripheralReset) { Module(new MatchingGmacCpu(config)) }
    val uartAdmission = withReset(cpuPeripheralReset) {
        Module(new soc.ip.clock.ClockRegisterAdmission)
    }
    uartAdmission.io.upstream <> platform.io.externalUartRegisters.get
    service.uart <> uartAdmission.io.downstream
    uartAdmission.io.quiesce := service.uartQuiesce
    uartAdmission.io.isolate := service.uartIsolate
    uartAdmission.io.downstreamIdle := service.uartIdle
    service.uartWake := withReset(cpuPeripheralReset) { RegNext(uartAdmission.io.wake, false.B) }
    service.uartDrained := withReset(cpuPeripheralReset) { RegNext(uartAdmission.io.drained, false.B) }
    gmac.io.registers <> platform.io.ethernetRegisters.get
    gmac.io.streams <> platform.io.ethernetStreams.get
    service.gmac <> gmac.io.service
    platform.io.sources := (gmac.io.irq.asUInt << 4) | (service.cmuIrq.asUInt << 6)

    io.commit.get := platform.io.commit
    io.trap.get := platform.io.trap
    io.fetchPc.get := platform.io.fetchPc
    io.fetchWait.get := platform.io.fetchWait
    io.cacheProfile.get := platform.io.activity.get.coherentCacheProfile
    io.headProfile.get := platform.io.activity.get.headProfile
    service.cpuMemoryFire := platform.io.activity.get.cpuMemoryFire
    service.memoryBusy := platform.io.activity.get.memoryBusy
    def tap[T <: Data](signal: T): T = BoringUtils.bore(signal)
    val packet = platform.packetDma.get
    val cache = platform.privateCache.get
    service.memoryDmaActive := tap(platform.dma.io.active)
    service.packetDmaActive := tap(packet.io.active)
    service.packetDmaIrq := tap(packet.io.irq)
    service.gmacMmioValid := platform.io.ethernetRegisters.get.request.valid
    service.packetRequestFire := (tap(packet.io.memory.request.valid) && tap(packet.io.memory.request.ready))
    service.packetRequestValid := tap(packet.io.memory.request.valid)
    service.packetRequestReady := tap(packet.io.memory.request.ready)
    service.packetRequestWrite := tap(packet.io.memory.request.bits.write)
    service.packetRequestAddress := tap(packet.io.memory.request.bits.address)
    service.packetRequestData := tap(packet.io.memory.request.bits.data)
    service.packetRequestMask := tap(packet.io.memory.request.bits.byteEnable)
    service.packetRequestSize := tap(packet.io.memory.request.bits.size)
    service.packetResponseFire := (tap(packet.io.memory.response.valid) && tap(packet.io.memory.response.ready))
    service.packetResponseValid := tap(packet.io.memory.response.valid)
    service.packetResponseReady := tap(packet.io.memory.response.ready)
    service.packetResponseData := tap(packet.io.memory.response.bits.data)
    service.packetResponseError := tap(packet.io.memory.response.bits.error)
    service.scalarDmaFire := (tap(platform.shared.io.dma.request.valid) && tap(platform.shared.io.dma.request.ready))
    service.lineDmaFire := (tap(platform.dma.io.line.get.request.valid) && tap(platform.dma.io.line.get.request.ready))
    val line = platform.dma.io.line.get
    service.lineRequestValid := tap(line.request.valid)
    service.lineRequestReady := tap(line.request.ready)
    service.lineRequestTag := tap(line.request.bits.tag)
    service.lineRequestAddress := tap(line.request.bits.address)
    service.lineRequestWrite := tap(line.request.bits.write)
    val lineRequestData = tap(line.request.bits.data)
    val lineResponseData = tap(line.response.bits.data)
    for (i <- 0 until 8) {
        service.lineRequestData.words(i) := lineRequestData(64 * i + 63, 64 * i)
        service.lineResponseData.words(i) := lineResponseData(64 * i + 63, 64 * i)
    }
    service.lineResponseFire := tap(line.response.valid) && tap(line.response.ready)
    service.lineResponseValid := tap(line.response.valid)
    service.lineResponseReady := tap(line.response.ready)
    service.lineResponseTag := tap(line.response.bits.tag)
    service.lineResponseError := tap(line.response.bits.error)
    service.probeFire := (tap(cache.io.tl.b.valid) && tap(cache.io.tl.b.ready))
    service.probeReplyDataFire := (tap(cache.io.tl.c.valid) && tap(cache.io.tl.c.ready)) &&
        tap(cache.io.tl.c.bits.opcode) === soc.bus.tilelink.TLOpcode.ProbeAckData
    service.jtagRequestFire := (tap(platform.jtagLoader.get.io.memory.request.valid) && tap(platform.jtagLoader.get.io.memory.request.ready))
    service.jtagRequestValid := tap(platform.jtagLoader.get.io.memory.request.valid)
    service.jtagRequestReady := tap(platform.jtagLoader.get.io.memory.request.ready)
    service.jtagRequestAddress := tap(platform.jtagLoader.get.io.memory.request.bits.address)
    service.jtagRequestWrite := tap(platform.jtagLoader.get.io.memory.request.bits.write)
    service.jtagRequestData := tap(platform.jtagLoader.get.io.memory.request.bits.data)
    service.jtagRequestSize := tap(platform.jtagLoader.get.io.memory.request.bits.size)
    service.jtagRequestMask := tap(platform.jtagLoader.get.io.memory.request.bits.byteEnable)
    service.jtagResponseFire := (tap(platform.jtagLoader.get.io.memory.response.valid) && tap(platform.jtagLoader.get.io.memory.response.ready))
    service.jtagResponseValid := tap(platform.jtagLoader.get.io.memory.response.valid)
    service.jtagResponseReady := tap(platform.jtagLoader.get.io.memory.response.ready)
    service.jtagResponseData := tap(platform.jtagLoader.get.io.memory.response.bits.data)
    service.jtagResponseError := tap(platform.jtagLoader.get.io.memory.response.bits.error)

    // Check the service model without adding any ready/valid path or queue.
    withReset(cpuPeripheralReset) {
        for (port <- Seq(service.uart, service.cmu)) {
            val busy = RegInit(false.B)
            when(port.request.fire) {
                assert(!busy, "external peripheral exceeded native one-credit CDC contract")
                busy := true.B
            }
            when(port.response.valid) { assert(busy, "unowned/zero-cycle external peripheral response") }
            when(port.response.fire) { busy := false.B }
            val stalled = RegNext(port.response.valid && !port.response.ready, false.B)
            val held = RegEnable(port.response.bits, port.response.valid && !port.response.ready)
            when(stalled) {
                assert(port.response.valid && port.response.bits.asUInt === held.asUInt,
                    "external peripheral changed a held response")
            }
        }
    }
    MatchingFabricAudit.capture(this, config)
}
