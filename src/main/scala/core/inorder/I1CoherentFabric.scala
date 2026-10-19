package soc.core.inorder

import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.ip.axi.Axi4MemoryPort
import soc.ip.bus.RegisterPort
import soc.ip.tilelink.{TwoMasterTileLinkArbiter, RegisteredTileLinkBoundary}

/** Two private exclusive caches, bounded two-way directory (I+D capacity),
  * CPU/DMA atomic exclusion and coherent JTAG/network access. Backing DDR
  * remains TL-UH: B/C/E are terminated ONLY by the Home, not tied off at L1.
  */
class I1CoherentFabric(p: FiveStageSocConfig, simulationRomInit: Boolean = false) extends Module {
    require(p.core.coherentCaches)
    val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val clients = Vec(2, Flipped(new TLBundle(params)))
        val lineGrants = if (p.core.coherentLineGrants)
            Some(Vec(2, Decoupled(new soc.ip.tilelink.LineGrant(params)))) else None
        val uncached = Vec(2, Flipped(new I1DataPort))
        val networkMemory = Flipped(new RegisterPort)
        val loaderMemory = Flipped(new RegisterPort)
        val clearReservation = Input(Bool())
        val registers = new RegisterPort
        val ddrAxi = new Axi4MemoryPort(32, 4)
        val romInitialize = if (p.withBootRom && simulationRomInit)
            Some(Input(Valid(new FiveStageRomInitialization(p.bootRomBytes)))) else None
    })
    val home = Module(new I1CoherentLineHome(params, p.ddrBase, p.ddrBytes, nClients = 2,
        trackedLines = 2 * p.core.dataCacheBytes / 64, trackedWays = 2 * p.core.coherentCacheWays,
        rawResponseMetadata = true, tagConfig = soc.core.ooo.CacheTagConfig.Aperture,
        parallelQualification = p.core.coherentControlCuts,
        ordinaryWritePipeline = p.core.coherentBandwidth,
        lineDispatchFlow = p.core.coherentBandwidth, wholeLineRead = p.core.coherentWholeLine,
        internalLineGrant = p.core.coherentLineGrants,
        writebackOverlap = p.core.coherentWritebackOverlap, readOverlap = p.core.coherentReadOverlap))
    io.lineGrants.foreach(_ <> home.io.lineGrants.get)
    for (i <- 0 until 2) {
        if (p.fabricTimingCuts) {
            val cut = Module(new I1RegisteredCoherentBoundary(params))
            cut.io.upstream <> io.clients(i); home.io.clients(i) <> cut.io.downstream
        } else home.io.clients(i) <> io.clients(i)
    }
    val cpu = Module(new I1SharedDataArbiter(registerResponseOwners = true))
    for (i <- 0 until 2) {
        if (p.fabricTimingCuts) {
            val nativeCut = Module(new I1RegisteredDataBoundary(preparePayload = p.core.coherentControlCuts))
            nativeCut.io.upstream <> io.uncached(i)
            cpu.io.clients(i) <> nativeCut.io.downstream
        } else cpu.io.clients(i) <> io.uncached(i)
    }
    val devices = Module(new I1CoherentDeviceFrontEnd(p.fabricTimingCuts && p.core.coherentControlCuts,
        compactHandoff = p.fabricTimingCuts && p.core.coherentBandwidth))
    devices.io.network <> io.networkMemory; devices.io.loader <> io.loaderMemory
    val atomic = Module(new I1AtomicDataMemory(p.ddrBase, p.ddrBytes, registerResponseOwners = true))
    atomic.io.cpu <> cpu.io.memory; atomic.io.dma <> devices.io.memory
    atomic.io.clearReservation := io.clearReservation
    if (p.fabricTimingCuts) {
        val ownershipCut = Module(new I1RegisteredDataBoundary(preparePayload = p.core.coherentControlCuts))
        ownershipCut.io.upstream <> atomic.io.memory
        home.io.upstream <> ownershipCut.io.downstream
    } else home.io.upstream <> atomic.io.memory
    // Uncached instruction reads and CPU AMOs also need to see a dirty D line.
    home.io.upstreamRequestCpu := false.B
    home.io.drainRequest := false.B
    // The Home drains direction changes/MMIO/probes. DDR has one actual AXI
    // write owner, executing accepted writes in order, so a same-direction
    // write cohort may occupy the existing bridge slots without posted ACKs.
    val ordinary = Module(new I1OrderedTileLinkBridge(entries = 4, params = params,
        orderedWrites = p.core.coherentBandwidth,
        allowWriteErrors = true, allowPartialWrites = true))
    if (p.fabricTimingCuts) {
        // Break the ordinary return-order mux -> Home -> atomic owner -> CPU
        // owner -> D-MMU cone. The coherent hit/refill path does not cross it.
        // Home permission/directory lookup owns VALID, not every payload FF.
        // Prepare only empty/vacated slots using the existing queue contract;
        // no posted ACK, borrowed credit, extra slot or changed acceptance edge.
        val ordinaryCut = Module(new I1RegisteredDataBoundary(preparePayload = p.core.coherentControlCuts))
        ordinaryCut.io.upstream <> home.io.downstream
        ordinary.io.data <> ordinaryCut.io.downstream
    } else ordinary.io.data <> home.io.downstream
    val route = Module(new FiveStageTileLinkRoute(params, p.ddrBase, p.ddrBytes,
        allowRegisters = true, registeredAdmission = p.core.fpgaTimingCuts))
    if (p.withBootRom) {
        val boot = Module(new FiveStageBootRoute(params, p.bootRomBase, p.bootRomBytes))
        val rom = Module(new FiveStageBootRom(params, p.bootRomBase, p.bootRomBytes,
            p.bootRomFile, simulationRomInit))
        boot.io.host <> ordinary.io.tl; route.io.host <> boot.io.downstream
        rom.io.ports(0) <> boot.io.rom
        val unused = rom.io.ports(1)
        unused.a.valid := false.B; unused.a.bits := 0.U.asTypeOf(unused.a.bits)
        unused.d.ready := true.B; unused.b.ready := true.B
        unused.c.valid := false.B; unused.c.bits := 0.U.asTypeOf(unused.c.bits)
        unused.e.valid := false.B; unused.e.bits := 0.U.asTypeOf(unused.e.bits)
        io.romInitialize.foreach(rom.io.initialize.get := _)
    } else route.io.host <> ordinary.io.tl
    io.registers <> route.io.registers
    val memory = Module(new TwoMasterTileLinkArbiter(params))
    memory.io.masters(0) <> home.io.line; memory.io.masters(1) <> route.io.memory
    val useAxiPreflight = p.fabricTimingCuts && p.core.fpgaTimingCuts
    val preparedA = Wire(new I1AxiPreflight(32))
    preparedA := 0.U.asTypeOf(preparedA)
    val backing = if (useAxiPreflight) {
        val boundary = Module(new I1RegisteredAxiRequestBoundary(memory.managerParams, 32,
            p.ddrBase, p.ddrBytes, 8))
        boundary.io.upstream <> memory.io.manager
        preparedA := boundary.io.preflight
        boundary.io.downstream
    } else if (p.fabricTimingCuts) {
        val boundary = Module(new RegisteredTileLinkBoundary(memory.managerParams))
        boundary.io.upstream <> memory.io.manager
        boundary.io.downstream
    } else memory.io.manager
    val bridge = Module(new I1TileLinkAxi4OutstandingBridge(memory.managerParams, 32, 4, 8,
        0, 0, 0, p.ddrBase, p.ddrBytes, 2, maxOutstandingWrites = 1, unorderedResponses = true,
        lineReadChannel = p.core.coherentWholeLine, parallelAdmission = p.core.fpgaTimingCuts,
        registeredPreflight = useAxiPreflight))
    bridge.io.tl <> backing; io.ddrAxi <> bridge.io.axi
    bridge.io.ordinaryPreflight.foreach(_ := preparedA)
    if (p.core.coherentWholeLine) {
        // Same two DDR owners. Request-only timing cut replaces the reader's
        // old dispatch storage; the retained DDR payload is not duplicated.
        if (useAxiPreflight) {
            val lineCut = Module(new I1RegisteredAxiLineRequestBoundary(32, p.ddrBase, p.ddrBytes, 8))
            lineCut.io.upstream <> home.io.lineRead.get
            bridge.io.lineRead.get <> lineCut.io.downstream
            bridge.io.linePreflight.get := lineCut.io.preflight
        } else {
            val lineCut = Module(new I1RegisteredLineReadRequestBoundary)
            lineCut.io.upstream <> home.io.lineRead.get
            bridge.io.lineRead.get <> lineCut.io.downstream
        }
    }
}
