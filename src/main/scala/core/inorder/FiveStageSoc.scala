package soc.core.inorder

import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.ip.axi.Axi4MemoryPort
import soc.ip.bus.{RegisterPort, RegisterResponse}
import soc.ip.tilelink.TwoMasterTileLinkArbiter
import soc.ip.timer.MachineTimer
import soc.ip.uart.UartConsole
import soc.ip.interrupt.Plic
import soc.ip.debug.{DebugDmiPort, JtagRamLoader}
import soc.core.ooo.{TileLinkAxi4BurstBridge, TileLinkAxi4OutstandingBridge}

/** Independent bare-metal assembly; existing OoO top/defaults are deliberately untouched.
  * BootROM or preloaded DDR; optional M/S/U, Sv39, PMP, boot-owned JTAG and M/S PLIC. No DMA.
  * AXI is in the CPU domain; reuse the board's existing AXI CDC/converter/MIG downstream.
  */
case class FiveStageSocConfig(
    core: FiveStageConfig = FiveStageConfig(resetVector = BigInt("10000", 16),
        trapVector = BigInt("80200100", 16), cacheableBase = BigInt("80200000", 16),
        cacheableBytes = BigInt(1) << 31),
    ddrBase: BigInt = BigInt("80200000", 16),
    ddrBytes: BigInt = BigInt(1) << 31,
    clockHz: Int = 100000000,
    uartBaud: Int = 460800,
    withUart: Boolean = true,
    withTimer: Boolean = true,
    withInterrupts: Boolean = true,
    ddrSlots: Int = 2,
    withBootRom: Boolean = true,
    bootRomBase: BigInt = BigInt("10000", 16),
    bootRomBytes: Int = 4096,
    bootRomFile: String = "src/main/resources/inorder/bootrom.hex",
    withJtagLoader: Boolean = false,
    jtagDownloadBytes: BigInt = BigInt(64) << 20,
    plicSources: Int = 8,
    plicPriorityBits: Int = 3,
    fabricTimingCuts: Boolean = false,
    managedPeripherals: Boolean = false,
    withNetwork: Boolean = false,
    networkDmaBase: BigInt = BigInt("10005000", 16)
) {
    require(core.xlen == 64, "initial SoC reuses the existing 64-bit DDR bridge")
    require(!fabricTimingCuts || core.fpgaTimingCuts)
    require(!withNetwork || (managedPeripherals && core.coherentCaches && withInterrupts && plicSources >= 7),
        "live network DMA requires TL-C, managed clocks and PLIC sources through7")
    require(!managedPeripherals || (withUart && (!withInterrupts || plicSources >= 7)),
        "managed UART/CMU may be used without MAC; CMU retains PLIC source7")
    require(networkDmaBase >= BigInt("10004000", 16) && networkDmaBase % 4096 == 0 &&
        networkDmaBase + 4096 <= BigInt("10040000", 16), "network DMA must not alias boot/JTAG/MAC")
    require(core.cacheLineBytes <= 128, "reused fabric supports at most 128-byte lines")
    require(ddrBase >= 0 && ddrBase % 4096 == 0 && ddrBytes >= 4096 &&
        ddrBytes <= (BigInt(1) << 31) && (ddrBytes & (ddrBytes - 1)) == 0)
    require(ddrBase + ddrBytes < (BigInt(1) << 64))
    require(bootRomBytes >= 1024 && isPow2(bootRomBytes) && bootRomBase >= 0 && bootRomBase % bootRomBytes == 0 &&
        bootRomBase + bootRomBytes <= BigInt("02000000", 16))
    require(if (withBootRom) core.resetVector == bootRomBase && bootRomFile.nonEmpty
        else core.resetVector >= ddrBase && core.resetVector < ddrBase + ddrBytes)
    require(!withJtagLoader || (withBootRom && ddrBase + jtagDownloadBytes < (BigInt(1) << 32) &&
        jtagDownloadBytes >= 4 && jtagDownloadBytes % 4 == 0 && jtagDownloadBytes <= ddrBytes),
        "boot-only JTAG SBA is 32-bit; the independent DDR map remains 64-bit/2 GiB")
    require(plicSources >= 3 && plicSources <= 1023 && plicPriorityBits >= 1 && plicPriorityBits <= 7)
    require(core.cacheableBase >= ddrBase && core.cacheableBase + core.cacheableBytes <= ddrBase + ddrBytes)
    require(clockHz > 0 && uartBaud > 0 && uartBaud.toLong * 16 <= clockHz)
    require(Set(1, 2).contains(ddrSlots), "at most the existing I/D cache owners; no enlarged queues")
    require(ddrBase >= BigInt("10004000", 16), "DDR overlaps the UART/boot-control/JTAG MMIO map")
}

/** One ordered peripheral owner. Disabled IP windows return errors, never hang or instantiate the IP. */
class FiveStagePeripherals(p: FiveStageSocConfig) extends Module {
    val io = IO(new Bundle {
        val registers = Flipped(new RegisterPort)
        val uartRx = Input(Bool()); val uartTx = Output(Bool())
        val uartIrq = Output(Bool()); val timerIrq = Output(Bool()); val softwareIrq = Output(Bool())
        val externalIrq = Input(Bool()); val machineExternalIrq = Output(Bool())
        val supervisorExternalIrq = Output(Bool())
        val ddrReady = Input(Bool()); val resetFault = Input(Bool())
        val loaderControl = new RegisterPort
        val invalidateDownloadCache = Output(Bool())
        val time = Output(UInt(64.W))
        val externalUart = if (p.managedPeripherals) Some(new RegisterPort) else None
        val externalUartIrq = if (p.managedPeripherals) Some(Input(Bool())) else None
        val gmacControl = if (p.withNetwork) Some(new RegisterPort) else None
        val cmuControl = if (p.managedPeripherals) Some(new RegisterPort) else None
        val cmuIrq = if (p.managedPeripherals && !p.withNetwork) Some(Input(Bool())) else None
        val networkDmaControl = if (p.withNetwork) Some(new RegisterPort) else None
        val networkIrqs = if (p.withNetwork) Some(Input(UInt(3.W))) else None
    })
    val uart = if (p.withUart && !p.managedPeripherals) Some(Module(new UartConsole(clockHz = p.clockHz,
        referenceClockHz = p.uartBaud * 16))) else None
    val uartPort = io.externalUart.orElse(uart.map(_.io.mmio))
    val timer = if (p.withTimer) Some(Module(new MachineTimer)) else None
    val plic = if (p.withInterrupts) Some(Module(new Plic(p.plicSources,
        if (p.core.withSupervisor) 2 else 1, p.plicPriorityBits))) else None
    io.uartTx := uart.map(_.io.tx).getOrElse(true.B)
    io.uartIrq := io.externalUartIrq.getOrElse(uart.map(_.io.irq).getOrElse(false.B))
    plic.foreach { controller =>
        controller.io.levels.foreach(_ := false.B)
        controller.io.levels(1) := io.externalIrq
        controller.io.levels(3) := io.uartIrq
        if (p.withNetwork) {
            controller.io.levels(5) := io.networkIrqs.get(0)
            controller.io.levels(6) := io.networkIrqs.get(1)
            controller.io.levels(7) := io.networkIrqs.get(2)
        }
        io.cmuIrq.foreach(controller.io.levels(7) := _)
    }
    io.machineExternalIrq := plic.map(_.io.irq(0)).getOrElse(false.B)
    io.supervisorExternalIrq := (if (p.core.withSupervisor) plic.map(_.io.irq(1)).getOrElse(false.B)
        else false.B)
    io.timerIrq := timer.map(_.io.irq).getOrElse(false.B)
    io.time := timer.map(_.io.timeValue).getOrElse(0.U)
    uart.foreach(_.io.rx := io.uartRx); timer.foreach(_.io.tick := true.B)
    val msip = if (p.withInterrupts) Some(RegInit(false.B)) else None
    io.softwareIrq := msip.getOrElse(false.B)
    val active = RegInit(false.B)
    io.invalidateDownloadCache := RegNext(io.loaderControl.request.fire &&
        io.loaderControl.request.bits.address === "h10003008".U && io.loaderControl.request.bits.write &&
        (io.loaderControl.request.bits.data(31, 0) === 1.U ||
            io.loaderControl.request.bits.data(31, 0) === 2.U), false.B)
    val owner = Reg(UInt(3.W))
    val r = io.registers.request.bits
    def window(base: BigInt, bytes: BigInt): Bool = if (p.core.fpgaTimingCuts)
        I1AddressWindow.contains(r.address, base, bytes)
        else r.address >= base.U && r.address < (base + bytes).U(65.W)
    val uartHit = p.withUart.B && window(BigInt("10000000", 16), 8)
    val timerHit = p.withTimer.B && (r.address === "h02004000".U || r.address === "h02004004".U ||
        r.address === "h0200bff8".U || r.address === "h0200bffc".U)
    val plicHit = p.withInterrupts.B && window(BigInt("0c000000", 16), BigInt("04000000", 16))
    val loaderHit = p.withJtagLoader.B && window(BigInt("10003000", 16), 64)
    val gmacHit = p.withNetwork.B && window(BigInt("10040000", 16), 4096)
    val cmuHit = p.managedPeripherals.B && window(BigInt("10080000", 16), 4096)
    val dmaHit = p.withNetwork.B && window(p.networkDmaBase, 256)
    val hits = Seq(uartHit, timerHit, false.B, plicHit, loaderHit, gmacHit, cmuHit, dmaHit)
    val anyHit = hits.reduce(_ || _)
    val selected = if (p.core.fpgaTimingCuts)
        Mux(anyHit, Mux1H(hits.zipWithIndex.map { case (hit, number) => hit -> number.U(3.W) }), 2.U)
        else Mux(uartHit, 0.U, Mux(timerHit, 1.U, Mux(plicHit, 3.U, Mux(loaderHit, 4.U,
            Mux(gmacHit, 5.U, Mux(cmuHit, 6.U, Mux(dmaHit, 7.U, 2.U)))))))
    if (p.core.fpgaTimingCuts) when(io.registers.request.valid && !reset.asBool) {
        assert(PopCount(hits) <= 1.U, "peripheral windows must not alias")
    }
    val local = Reg(new RegisterResponse)
    val msipLegal = p.withInterrupts.B && r.address === "h02000000".U && r.size === 2.U &&
        r.byteEnable === 15.U
    val bootLegal = p.withBootRom.B && !r.write && r.size === 3.U && r.byteEnable === 255.U &&
        (r.address === "h10002000".U || r.address === "h10002008".U)
    val bootStatus = Cat(p.withUart.B, io.resetFault, p.withJtagLoader.B, io.ddrReady)
    val ready = Seq(uartPort.map(_.request.ready).getOrElse(false.B),
        timer.map(_.io.mmio.request.ready).getOrElse(false.B), true.B,
        plic.map(_.io.mmio.request.ready).getOrElse(false.B), io.loaderControl.request.ready,
        io.gmacControl.map(_.request.ready).getOrElse(false.B),
        io.cmuControl.map(_.request.ready).getOrElse(false.B),
        io.networkDmaControl.map(_.request.ready).getOrElse(false.B))
    io.registers.request.ready := !active && (if (p.core.fpgaTimingCuts)
        (!anyHit || Mux1H(hits.zip(ready))) else VecInit(ready)(selected))
    for ((port, number) <- Seq(uartPort -> 0, timer.map(_.io.mmio) -> 1,
        plic.map(_.io.mmio) -> 3, Some(io.loaderControl) -> 4, io.gmacControl -> 5,
        io.cmuControl -> 6, io.networkDmaControl -> 7); ip <- port) {
        ip.request.valid := io.registers.request.valid && !active &&
            (if (p.core.fpgaTimingCuts) hits(number) else selected === number.U)
        ip.request.bits := r
        ip.response.ready := active && owner === number.U && io.registers.response.ready
    }
    io.registers.response.valid := active && MuxLookup(owner, true.B)(Seq(
        0.U -> uartPort.map(_.response.valid).getOrElse(false.B),
        1.U -> timer.map(_.io.mmio.response.valid).getOrElse(false.B),
        3.U -> plic.map(_.io.mmio.response.valid).getOrElse(false.B), 4.U -> io.loaderControl.response.valid,
        5.U -> io.gmacControl.map(_.response.valid).getOrElse(false.B),
        6.U -> io.cmuControl.map(_.response.valid).getOrElse(false.B),
        7.U -> io.networkDmaControl.map(_.response.valid).getOrElse(false.B)))
    io.registers.response.bits := MuxLookup(owner, local)(Seq(
        0.U -> uartPort.map(_.response.bits).getOrElse(local),
        1.U -> timer.map(_.io.mmio.response.bits).getOrElse(local),
        3.U -> plic.map(_.io.mmio.response.bits).getOrElse(local), 4.U -> io.loaderControl.response.bits,
        5.U -> io.gmacControl.map(_.response.bits).getOrElse(local),
        6.U -> io.cmuControl.map(_.response.bits).getOrElse(local),
        7.U -> io.networkDmaControl.map(_.response.bits).getOrElse(local)))
    when(io.registers.request.fire) {
        active := true.B; owner := selected
        local.error := !(msipLegal || bootLegal)
        local.data := Mux(bootLegal, Mux(r.address === "h10002000".U, bootStatus, p.ddrBase.U),
            msip.getOrElse(false.B))
        msip.foreach { bit => when(msipLegal && r.write) { bit := r.data(0) } }
    }
    when(io.registers.response.fire) { active := false.B }
}

class FiveStageSoc(val p: FiveStageSocConfig, simulationRomInit: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val ddrAxi = new Axi4MemoryPort(32, 4)
        val uartRx = Input(Bool()); val uartTx = Output(Bool()); val externalIrq = Input(Bool())
        val clockLocked = Input(Bool()); val ddrReady = Input(Bool())
        val resetHeld = Output(Bool()); val resetFault = Output(Bool())
        val jtagLinkUp = Input(Bool()); val jtagDmi = Flipped(new DebugDmiPort(7))
        val externalUart = if (p.managedPeripherals) Some(new RegisterPort) else None
        val externalUartIrq = if (p.managedPeripherals) Some(Input(Bool())) else None
        val gmacControl = if (p.withNetwork) Some(new RegisterPort) else None
        val cmuControl = if (p.managedPeripherals) Some(new RegisterPort) else None
        val cmuIrq = if (p.managedPeripherals && !p.withNetwork) Some(Input(Bool())) else None
        val networkDmaControl = if (p.withNetwork) Some(new RegisterPort) else None
        val networkIrqs = if (p.withNetwork) Some(Input(UInt(3.W))) else None
        // Simulation-only coherent agent permits independent CPU-result readback;
        // it is absent from production exports unless real network DMA is enabled.
        val networkMemory = if (p.withNetwork || (p.core.coherentCaches && simulationRomInit))
            Some(Flipped(new RegisterPort)) else None
        val romInitialize = if (p.withBootRom && simulationRomInit)
            Some(Input(Valid(new FiveStageRomInitialization(p.bootRomBytes)))) else None
        val retire = Valid(new FiveStageRetire(p.core))
        val trapTaken = Output(Bool()); val trapPc = Output(UInt(64.W)); val trapCause = Output(UInt(64.W))
        val cycles = Output(UInt(64.W)); val instructions = Output(UInt(64.W))
    })
    val startup = Module(new FiveStageStartup(p.withBootRom))
    startup.io.clockLocked := io.clockLocked; startup.io.ddrReady := io.ddrReady
    io.resetHeld := startup.io.held; io.resetFault := startup.io.fault
    val coreReset = reset.asBool || startup.io.held
    val core = withReset(coreReset) { Module(new FiveStageCachedCore(p.core, p.withJtagLoader)) }
    val peripherals = Module(new FiveStagePeripherals(p))
    peripherals.io.uartRx := io.uartRx; io.uartTx := peripherals.io.uartTx
    peripherals.io.externalIrq := io.externalIrq
    peripherals.io.ddrReady := startup.io.memoryReady; peripherals.io.resetFault := startup.io.fault
    core.io.invalidateData.foreach(_ := peripherals.io.invalidateDownloadCache)
    // Coherent configurations route live DMA through the Home/atomic boundary below.
    core.io.invalidateReservation.foreach(_ := false.B)
    core.io.time := peripherals.io.time
    core.io.externalIrq := peripherals.io.machineExternalIrq
    core.io.supervisorExternalIrq.foreach(_ := peripherals.io.supervisorExternalIrq)
    core.io.timerIrq := p.withInterrupts.B && peripherals.io.timerIrq
    core.io.softwareIrq := p.withInterrupts.B && peripherals.io.softwareIrq
    if (p.managedPeripherals) {
        io.externalUart.get <> peripherals.io.externalUart.get
        peripherals.io.externalUartIrq.get := io.externalUartIrq.get
    }
    if (p.managedPeripherals) {
        io.cmuControl.get <> peripherals.io.cmuControl.get
        io.cmuIrq.foreach(peripherals.io.cmuIrq.get := _)
    }
    if (p.withNetwork) {
        io.gmacControl.get <> peripherals.io.gmacControl.get
        io.networkDmaControl.get <> peripherals.io.networkDmaControl.get
        peripherals.io.networkIrqs.get := io.networkIrqs.get
    }
    if (p.core.coherentCaches) {
        val fabric = Module(new I1CoherentFabric(p, simulationRomInit))
        for (i <- 0 until 2) {
            fabric.io.clients(i) <> core.io.coherent.get(i)
            fabric.io.uncached(i) <> core.io.uncached.get(i)
            core.io.lineGrants.foreach(_(i) <> fabric.io.lineGrants.get(i))
        }
        for (port <- Seq(core.io.instructionMemory, core.io.dataMemory)) {
            port.request.ready := false.B
            port.response.valid := false.B
            port.response.bits := 0.U.asTypeOf(port.response.bits)
        }
        fabric.io.clearReservation := core.io.clearCoherentReservation.get
        peripherals.io.registers <> fabric.io.registers
        io.ddrAxi <> fabric.io.ddrAxi
        io.romInitialize.foreach(fabric.io.romInitialize.get := _)
        if (io.networkMemory.isDefined) fabric.io.networkMemory <> io.networkMemory.get
        else {
            fabric.io.networkMemory.request.valid := false.B
            fabric.io.networkMemory.request.bits := 0.U.asTypeOf(fabric.io.networkMemory.request.bits)
            fabric.io.networkMemory.response.ready := true.B
        }
        if (p.withJtagLoader) {
            val loader = Module(new I1JtagRamLoader(p.ddrBase, p.ddrBase + p.jtagDownloadBytes,
                timingCuts = p.core.fpgaTimingCuts))
            loader.io.dmi <> io.jtagDmi; loader.io.linkUp := io.jtagLinkUp
            loader.io.control <> peripherals.io.loaderControl
            fabric.io.loaderMemory <> loader.io.memory
        } else {
            io.jtagDmi.request.ready := false.B; io.jtagDmi.response.valid := false.B
            io.jtagDmi.response.bits := 0.U.asTypeOf(io.jtagDmi.response.bits)
            peripherals.io.loaderControl.request.ready := false.B
            peripherals.io.loaderControl.response.valid := false.B
            peripherals.io.loaderControl.response.bits := 0.U.asTypeOf(peripherals.io.loaderControl.response.bits)
            fabric.io.loaderMemory.request.valid := false.B
            fabric.io.loaderMemory.request.bits := 0.U.asTypeOf(fabric.io.loaderMemory.request.bits)
            fabric.io.loaderMemory.response.ready := true.B
        }
    } else {
    val adapters = Seq.fill(2)(Module(new FiveStageTileLink(p.core)))
    for ((adapter, port) <- adapters.zip(Seq(core.io.instructionMemory, core.io.dataMemory))) {
        adapter.io.native <> port
        adapter.io.native.request.valid := port.request.valid && !coreReset
        port.request.ready := adapter.io.native.request.ready && !coreReset
    }
    val routes = (0 until 2).map(i => Module(new FiveStageTileLinkRoute(adapters(i).params,
        p.ddrBase, p.ddrBytes, allowRegisters = i == 1, registeredAdmission = p.core.fpgaTimingCuts)))
    val arbiter = Module(new TwoMasterTileLinkArbiter(adapters.head.params))
    val rom = if (p.withBootRom) Some(Module(new FiveStageBootRom(adapters.head.params,
        p.bootRomBase, p.bootRomBytes, p.bootRomFile, simulationRomInit))) else None
    io.romInitialize.foreach { init => rom.get.io.initialize.get := init }
    for (i <- 0 until 2) {
        if (p.withBootRom) {
            val route = Module(new FiveStageBootRoute(adapters(i).params, p.bootRomBase, p.bootRomBytes))
            route.io.host <> adapters(i).io.tl; rom.get.io.ports(i) <> route.io.rom
            routes(i).io.host <> route.io.downstream
        } else { routes(i).io.host <> adapters(i).io.tl }
        arbiter.io.masters(i) <> routes(i).io.memory
    }
    val unused = routes.head.io.registers
    unused.request.ready := false.B; unused.response.valid := false.B
    unused.response.bits := 0.U.asTypeOf(unused.response.bits)
    val manager = if (p.withJtagLoader) {
        val loader = Module(new I1JtagRamLoader(p.ddrBase, p.ddrBase + p.jtagDownloadBytes,
                timingCuts = p.core.fpgaTimingCuts))
        loader.io.dmi <> io.jtagDmi; loader.io.linkUp := io.jtagLinkUp
        loader.io.control <> peripherals.io.loaderControl
        val adapter = Module(new FiveStageLoaderTileLink(arbiter.managerParams))
        adapter.io.registers <> loader.io.memory
        val shared = Module(new TwoMasterTileLinkArbiter(arbiter.managerParams))
        shared.io.masters(0) <> arbiter.io.manager; shared.io.masters(1) <> adapter.io.tl
        (shared.io.manager, shared.managerParams)
    } else {
        io.jtagDmi.request.ready := false.B; io.jtagDmi.response.valid := false.B
        io.jtagDmi.response.bits := 0.U.asTypeOf(io.jtagDmi.response.bits)
        peripherals.io.loaderControl.request.ready := false.B
        peripherals.io.loaderControl.response.valid := false.B
        peripherals.io.loaderControl.response.bits := 0.U.asTypeOf(peripherals.io.loaderControl.response.bits)
        (arbiter.io.manager, arbiter.managerParams)
    }
    peripherals.io.registers <> routes(1).io.registers
    val memoryLink = if (p.fabricTimingCuts) {
        val cut = Module(new soc.ip.tilelink.RegisteredTileLinkBoundary(manager._2))
        cut.io.upstream <> manager._1; cut.io.downstream
    } else manager._1
    val maxBeats = math.max(8, p.core.cacheLineBytes / 8)
    if (p.ddrSlots == 1) {
        if (p.core.fpgaTimingCuts) {
            val bridge = Module(new I1TileLinkAxi4BurstBridge(manager._2, 32, 4, maxBeats,
                axiAddressBase = p.ddrBase, axiWindowBytes = p.ddrBytes))
            bridge.io.tl <> memoryLink; io.ddrAxi <> bridge.io.axi
        } else {
            val bridge = Module(new TileLinkAxi4BurstBridge(manager._2, 32, 4, maxBeats,
                axiAddressBase = p.ddrBase, axiWindowBytes = p.ddrBytes))
            bridge.io.tl <> memoryLink; io.ddrAxi <> bridge.io.axi
        }
    } else {
        if (p.core.fpgaTimingCuts) {
            val bridge = Module(new I1TileLinkAxi4OutstandingBridge(manager._2, 32, 4, maxBeats,
                0, 0, 0, p.ddrBase, p.ddrBytes, 2, maxOutstandingWrites = 1, unorderedResponses = true,
                parallelAdmission = true))
            bridge.io.tl <> memoryLink; io.ddrAxi <> bridge.io.axi
        } else {
            val bridge = Module(new TileLinkAxi4OutstandingBridge(manager._2, 32, 4, maxBeats,
                0, 0, 0, p.ddrBase, p.ddrBytes, 2, maxOutstandingWrites = 1, unorderedResponses = true))
            bridge.io.tl <> memoryLink; io.ddrAxi <> bridge.io.axi
        }
    }
    }
    io.retire := core.io.retire; io.cycles := core.io.cycles; io.instructions := core.io.instructions
    io.trapTaken := core.io.trapTaken; io.trapPc := core.io.trapPc; io.trapCause := core.io.trapCause
}
