package soc.core.inorder

import chisel3._
import chisel3.util._
import soc.bus.tilelink.TLParams
import soc.ip.axi.Axi4MemoryPort
import soc.ip.bus.{HeldResponseCdcDataFifo, CdcLevel, CdcMailbox, CdcResetRelease, RegisterPort}
import soc.ip.tilelink.TileLinkClockDomainBoundary

/** A clear is ordered with D-uncached requests, rather than crossing as a lossy pulse. */
class I1OrderedDataClockEvent extends Bundle {
    val isClear = Bool()
    val request = new I1DataRequest
}

/** Two independent request/reply FIFOs. Only the D instance carries reservation clears.
  *
  * A pending clear wins over a new request. Clears may coalesce only while no
  * intervening request is accepted. At the fabric end, a clear waits for the
  * replies of all earlier requests: fabric admission is NOT atomic execution,
  * since registered request queues exist before AtomicMemory. This prevents an
  * old queued LR from establishing a reservation AFTER its clear was consumed.
  * Later requests cannot pass that clear. Ordinary request/reply traffic may
  * remain outstanding; coherent B/C/E never depend on this fence.
  */
class I1OrderedDataClockBoundary(depth: Int = 16, carriesClear: Boolean = false) extends RawModule {
    require(depth >= 4 && isPow2(depth))
    val cpuClock = IO(Input(Clock()))
    val fabricClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val cpu = IO(Flipped(new I1DataPort))
    val fabric = IO(new I1DataPort)
    val clearReservation = IO(Input(Bool()))
    val fabricClearReservation = IO(Output(Bool()))
    val cpuLinkReady = IO(Output(Bool()))
    val fabricLinkReady = IO(Output(Bool()))
    val cpuTransportEmpty = IO(Output(Bool()))
    val fabricTransportEmpty = IO(Output(Bool()))

    private val cpuRelease = Module(new CdcResetRelease)
    cpuRelease.clockIn := cpuClock; cpuRelease.asyncReset := commonColdReset
    private val fabricRelease = Module(new CdcResetRelease)
    fabricRelease.clockIn := fabricClock; fabricRelease.asyncReset := commonColdReset
    private val fabricReleasedInCpu = Module(new CdcLevel)
    fabricReleasedInCpu.clockIn := cpuClock; fabricReleasedInCpu.resetIn := cpuRelease.resetOut
    fabricReleasedInCpu.levelIn := !fabricRelease.resetOut.asBool
    private val cpuReleasedInFabric = Module(new CdcLevel)
    cpuReleasedInFabric.clockIn := fabricClock; cpuReleasedInFabric.resetIn := fabricRelease.resetOut
    cpuReleasedInFabric.levelIn := !cpuRelease.resetOut.asBool
    cpuLinkReady := !cpuRelease.resetOut.asBool && fabricReleasedInCpu.levelOut
    fabricLinkReady := !fabricRelease.resetOut.asBool && cpuReleasedInFabric.levelOut

    private val requests = Module(new HeldResponseCdcDataFifo((new I1OrderedDataClockEvent).getWidth, depth))
    requests.sourceClock := cpuClock; requests.destinationClock := fabricClock
    requests.commonReset := commonColdReset
    private val replies = Module(new HeldResponseCdcDataFifo((new I1DataResponse).getWidth, depth))
    replies.sourceClock := fabricClock; replies.destinationClock := cpuClock
    replies.commonReset := commonColdReset
    private val clearPending = withClockAndReset(cpuClock, cpuRelease.resetOut) { RegInit(false.B) }
    private val hasClear = carriesClear.B && (clearPending || clearReservation)
    private val event = Wire(new I1OrderedDataClockEvent)
    event.isClear := hasClear
    event.request := cpu.request.bits
    requests.source.valid := cpuLinkReady && (hasClear || cpu.request.valid)
    requests.source.bits := event.asUInt
    cpu.request.ready := cpuLinkReady && !hasClear && requests.source.ready
    withClockAndReset(cpuClock, cpuRelease.resetOut) {
        clearPending := hasClear && !requests.source.fire
        when(!carriesClear.B) { assert(!clearReservation, "I-uncached boundary cannot carry reservation clears") }
        when(hasClear) { assert(!cpu.request.fire, "request passed a pending reservation clear") }
    }
    replies.source.valid := fabricLinkReady && fabric.response.valid
    replies.source.bits := fabric.response.bits.asUInt
    fabric.response.ready := fabricLinkReady && replies.source.ready
    cpu.response.valid := cpuLinkReady && replies.destination.valid
    cpu.response.bits := replies.destination.bits.asTypeOf(cpu.response.bits)
    replies.destination.ready := cpuLinkReady && cpu.response.ready

    private val received = requests.destination.bits.asTypeOf(new I1OrderedDataClockEvent)
    // The finite cache/fabric owner queues bound this far below 2^16. This is
    // an accounting fence, not a new transaction owner or a one-request token.
    private val inFlight = withClockAndReset(fabricClock, fabricRelease.resetOut) { RegInit(0.U(16.W)) }
    private val accepted = withClockAndReset(fabricClock, fabricRelease.resetOut) { RegInit(0.U(32.W)) }
    private val replied = withClockAndReset(fabricClock, fabricRelease.resetOut) { RegInit(0.U(32.W)) }
    private val clearCanRun = inFlight === 0.U
    fabric.request.valid := fabricLinkReady && requests.destination.valid && !received.isClear
    fabric.request.bits := received.request
    requests.destination.ready := fabricLinkReady && Mux(received.isClear, clearCanRun, fabric.request.ready)
    fabricClearReservation := requests.destination.fire && received.isClear
    withClockAndReset(fabricClock, fabricRelease.resetOut) {
        when(fabric.request.fire) { accepted := accepted + 1.U }
        when(fabric.response.fire) { replied := replied + 1.U }
        assert(accepted - replied === inFlight, "uncached accepted/replied owner ledger diverged")
        when(fabric.request.fire =/= fabric.response.fire) {
            inFlight := Mux(fabric.request.fire, inFlight + 1.U, inFlight - 1.U)
        }
        when(fabric.response.fire) { assert(inFlight =/= 0.U, "uncached response has no accepted owner") }
        when(fabric.request.fire) { assert(inFlight =/= 65535.U, "uncached owner accounting overflow") }
        when(fabricClearReservation) {
            assert(carriesClear.B && accepted === replied && inFlight === 0.U,
                "reservation clear overtook an accepted request")
        }
    }
    cpuTransportEmpty := cpuLinkReady && !hasClear && requests.sourceIdle && replies.destinationIdle
    fabricTransportEmpty := fabricLinkReady && requests.destinationIdle && replies.sourceIdle
}

/** Shared pin contract; control/trace outputs live in the CPU domain unless noted. */
class I1IndependentClockSocIO(p: FiveStageSocConfig, simulationRomInit: Boolean = false,
    simulationAgent: Boolean = false) extends Bundle {
    val ddrAxi = new Axi4MemoryPort(32, 4) // fabric clock
    val uartRx = Input(Bool()); val uartTx = Output(Bool()) // fabric UART
    val externalIrq = Input(Bool())
    val clockLocked = Input(Bool()); val ddrReady = Input(Bool())
    val resetHeld = Output(Bool()); val resetFault = Output(Bool())
    val cpuLinkReady = Output(Bool()); val fabricLinkReady = Output(Bool())
    val cpuTransportEmpty = Output(Bool()); val fabricTransportEmpty = Output(Bool())
    val networkMemory = if (simulationAgent || simulationRomInit) Some(Flipped(new RegisterPort)) else None
    val romInitialize = if (p.withBootRom && simulationRomInit)
        Some(Input(Valid(new FiveStageRomInitialization(p.bootRomBytes)))) else None
    val retire = Valid(new FiveStageRetire(p.core))
    val trapTaken = Output(Bool()); val trapPc = Output(UInt(64.W)); val trapCause = Output(UInt(64.W))
    val cycles = Output(UInt(64.W)); val instructions = Output(UInt(64.W))
    val timeSnapshot = Output(UInt(64.W))
}

/** Explicit opt-in independent CPU/fabric clocks; existing assemblies/defaults are untouched.
  *
  * Both clocks must always run. commonColdReset is the ONLY reset operation and
  * must reset the external DDR model/controller's transaction epoch as well as
  * this core, caches, Home, bridges, peripherals and all transport FIFOs. Queue
  * empty is not a global drain proof. No hot reset, retention or clock gating.
  * Fabric clocks the existing Home, unchanged two DDR slots, ROM and MMIO.
  * Its declared timer/UART timebase is p.clockHz, not the variable CPU rate.
  * Gray buses and held mailbox data still require board-specific CDC timing
  * constraints and physical qualification; simulation cannot prove metastability.
  */
class I1IndependentClockSoc(val p: FiveStageSocConfig, depth: Int = 16,
    simulationRomInit: Boolean = false, simulationAgent: Boolean = false) extends RawModule {
    require(p.core.coherentCaches, "independent clocks require the existing two-client TL-C assembly")
    require(p.core.coherentControlCuts && p.core.coherentBandwidth,
        "clear-event admission requires occupancy-only buffered CPU/cache request admission")
    require(p.ddrSlots == 2, "independent-clock profile preserves the existing two DDR owners")
    require(!p.withJtagLoader && !p.withNetwork && !p.managedPeripherals,
        "first independent-clock profile excludes JTAG, network and managed peripheral event owners")
    require(depth >= 4 && isPow2(depth))
    val cpuClock = IO(Input(Clock()))
    val fabricClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val io = IO(new I1IndependentClockSocIO(p, simulationRomInit, simulationAgent))
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    private val cpuRelease = Module(new CdcResetRelease)
    cpuRelease.clockIn := cpuClock; cpuRelease.asyncReset := commonColdReset
    private val fabricRelease = Module(new CdcResetRelease)
    fabricRelease.clockIn := fabricClock; fabricRelease.asyncReset := commonColdReset
    private def level(input: Bool, clock: Clock, reset: AsyncReset): Bool = {
        val sync = Module(new CdcLevel)
        sync.clockIn := clock; sync.resetIn := reset; sync.levelIn := input
        sync.levelOut
    }
    private val coherent = Seq.fill(2)(Module(new TileLinkClockDomainBoundary(
        params, depth, heldResponseStorage = true)))
    private val uncached = (0 until 2).map(i => Module(new I1OrderedDataClockBoundary(depth, carriesClear = i == 1)))
    for (link <- coherent) {
        link.cpuClock := cpuClock; link.fabricClock := fabricClock; link.commonColdReset := commonColdReset
    }
    for (link <- uncached) {
        link.cpuClock := cpuClock; link.fabricClock := fabricClock; link.commonColdReset := commonColdReset
    }
    io.cpuLinkReady := (coherent.map(_.cpuLinkReady) ++ uncached.map(_.cpuLinkReady)).reduce(_ && _)
    io.fabricLinkReady := (coherent.map(_.fabricLinkReady) ++ uncached.map(_.fabricLinkReady)).reduce(_ && _)
    private val cpuStartup = withClockAndReset(cpuClock, cpuRelease.resetOut) {
        Module(new FiveStageStartup(p.withBootRom))
    }
    private val fabricStartup = withClockAndReset(fabricClock, fabricRelease.resetOut) {
        Module(new FiveStageStartup(p.withBootRom))
    }
    fabricStartup.io.clockLocked := level(io.clockLocked, fabricClock, fabricRelease.resetOut) && io.fabricLinkReady
    fabricStartup.io.ddrReady := level(io.ddrReady, fabricClock, fabricRelease.resetOut)
    cpuStartup.io.clockLocked := level(io.clockLocked, cpuClock, cpuRelease.resetOut) && io.cpuLinkReady &&
        level(!fabricStartup.io.held, cpuClock, cpuRelease.resetOut)
    cpuStartup.io.ddrReady := level(io.ddrReady, cpuClock, cpuRelease.resetOut)
    io.resetHeld := cpuStartup.io.held
    io.resetFault := cpuStartup.io.fault || level(fabricStartup.io.fault, cpuClock, cpuRelease.resetOut)
    private val coreReset = (cpuRelease.resetOut.asBool || cpuStartup.io.held).asAsyncReset
    private val core = withClockAndReset(cpuClock, coreReset) { Module(new FiveStageCachedCore(p.core)) }
    private val fabric = withClockAndReset(fabricClock, fabricRelease.resetOut) {
        Module(new I1CoherentFabric(p, simulationRomInit))
    }
    private val peripherals = withClockAndReset(fabricClock, fabricRelease.resetOut) {
        Module(new FiveStagePeripherals(p))
    }
    private val grants = if (p.core.coherentLineGrants) (0 until 2).map { i =>
        val fifo = Module(new HeldResponseCdcDataFifo(fabric.io.lineGrants.get(i).bits.getWidth, depth))
        fifo.sourceClock := fabricClock; fifo.destinationClock := cpuClock; fifo.commonReset := commonColdReset
        fifo.source.valid := fabric.io.lineGrants.get(i).valid && io.fabricLinkReady
        fifo.source.bits := fabric.io.lineGrants.get(i).bits.asUInt
        fabric.io.lineGrants.get(i).ready := fifo.source.ready && io.fabricLinkReady
        core.io.lineGrants.get(i).valid := fifo.destination.valid && io.cpuLinkReady
        core.io.lineGrants.get(i).bits := fifo.destination.bits.asTypeOf(core.io.lineGrants.get(i).bits)
        fifo.destination.ready := core.io.lineGrants.get(i).ready && io.cpuLinkReady
        fifo
    } else Seq.empty
    for (i <- 0 until 2) {
        coherent(i).cpu <> core.io.coherent.get(i); fabric.io.clients(i) <> coherent(i).fabric
        uncached(i).cpu <> core.io.uncached.get(i); fabric.io.uncached(i) <> uncached(i).fabric
        uncached(i).clearReservation := (if (i == 1) core.io.clearCoherentReservation.get else false.B)
    }
    fabric.io.clearReservation := uncached(1).fabricClearReservation
    core.io.invalidateReservation.foreach(_ := false.B)
    for (port <- Seq(core.io.instructionMemory, core.io.dataMemory)) {
        port.request.ready := false.B; port.response.valid := false.B
        port.response.bits := 0.U.asTypeOf(port.response.bits)
    }
    io.cpuTransportEmpty := io.cpuLinkReady && (coherent.map(_.cpuTransportEmpty) ++
        uncached.map(_.cpuTransportEmpty) ++ grants.map(_.destinationIdle)).reduce(_ && _)
    io.fabricTransportEmpty := io.fabricLinkReady && (coherent.map(_.fabricTransportEmpty) ++
        uncached.map(_.fabricTransportEmpty) ++ grants.map(_.sourceIdle)).reduce(_ && _)
    peripherals.io.registers <> fabric.io.registers
    io.ddrAxi <> fabric.io.ddrAxi
    peripherals.io.uartRx := io.uartRx; io.uartTx := peripherals.io.uartTx
    peripherals.io.externalIrq := level(io.externalIrq, fabricClock, fabricRelease.resetOut)
    peripherals.io.ddrReady := fabricStartup.io.memoryReady
    peripherals.io.resetFault := fabricStartup.io.fault ||
        level(cpuStartup.io.fault, fabricClock, fabricRelease.resetOut)
    core.io.externalIrq := level(peripherals.io.machineExternalIrq, cpuClock, cpuRelease.resetOut)
    core.io.supervisorExternalIrq.foreach(_ :=
        level(peripherals.io.supervisorExternalIrq, cpuClock, cpuRelease.resetOut))
    core.io.timerIrq := level(p.withInterrupts.B && peripherals.io.timerIrq, cpuClock, cpuRelease.resetOut)
    core.io.softwareIrq := level(p.withInterrupts.B && peripherals.io.softwareIrq, cpuClock, cpuRelease.resetOut)
    private val time = Module(new CdcMailbox(64))
    time.sourceClock := fabricClock; time.destinationClock := cpuClock; time.commonReset := commonColdReset
    time.source.valid := io.fabricLinkReady; time.source.bits := peripherals.io.time
    time.destination.ready := true.B
    private val timeSnapshot = withClockAndReset(cpuClock, cpuRelease.resetOut) {
        val captured = RegInit(0.U(64.W))
        when(time.destination.fire) { captured := time.destination.bits }
        captured
    }
    core.io.time := timeSnapshot; io.timeSnapshot := timeSnapshot
    io.romInitialize.foreach(fabric.io.romInitialize.get := _)
    io.networkMemory match {
        case Some(port) => fabric.io.networkMemory <> port
        case None =>
            fabric.io.networkMemory.request.valid := false.B
            fabric.io.networkMemory.request.bits := 0.U.asTypeOf(fabric.io.networkMemory.request.bits)
            fabric.io.networkMemory.response.ready := true.B
    }
    peripherals.io.loaderControl.request.ready := false.B
    peripherals.io.loaderControl.response.valid := false.B
    peripherals.io.loaderControl.response.bits := 0.U.asTypeOf(peripherals.io.loaderControl.response.bits)
    fabric.io.loaderMemory.request.valid := false.B
    fabric.io.loaderMemory.request.bits := 0.U.asTypeOf(fabric.io.loaderMemory.request.bits)
    fabric.io.loaderMemory.response.ready := true.B
    io.retire := core.io.retire; io.cycles := core.io.cycles; io.instructions := core.io.instructions
    io.trapTaken := core.io.trapTaken; io.trapPc := core.io.trapPc; io.trapCause := core.io.trapCause
}
