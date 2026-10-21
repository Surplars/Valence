package soc.platform

import chisel3._
import chisel3.util._
import soc.ip.axi.Axi4MemoryPort
import soc.ip.bus.CdcResetRelease
import soc.ip.clock.{ClockRateParams, ManagedPeripheralBank}
import soc.ip.debug.DebugDmiPort

class CommonRetireTrace extends Bundle {
    val pc = UInt(64.W)
    val instruction = UInt(32.W)
    val nextPc = UInt(64.W)
    val rd = UInt(5.W)
    val writesRd = Bool()
    val data = UInt(64.W)
}

/** One public platform, selected CPU-private tile, static independent clocks.
  * DDR AXI belongs to fabricClock; the initial target uses the same 250 MHz UI
  * clock, avoiding a redundant AXI CDC. Other clock choices require an external
  * qualified AXI crossing. All raw/CPU/fabric clocks must remain running.
  * This is a native tri-speed RGMII-edge/DMI/AXI assembly, not an FPGA pin/MMCM/MIG wrapper.
  */
class CommonMachinePlatform(
    val profile: CommonCpuProfile,
    romFiles: Seq[String] = Seq.empty,
    programmable: Boolean = false,
    hardwareClocks: Boolean = true,
    vivadoMemories: Boolean = false
) extends RawModule {
    val cpuClock = IO(Input(Clock()))
    val fabricClock = IO(Input(Clock()))
    val alwaysOnClock = IO(Input(Clock()))
    val rawUartClock = IO(Input(Clock()))
    val rawTxClock = IO(Input(Clock()))
    val rawRxClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val io = IO(new Bundle {
        val ddrAxi = new Axi4MemoryPort(32, profile.fpga.ddr.axiIdWidth)
        val ddrReady = Input(Bool())
        // Cold-start admission only; dropping this after startup cannot reset or cancel owners.
        val bootEnable = Input(Bool())
        val sources = Input(UInt(CommonPlatformAbi.interruptSources.W))
        val uartRx = Input(Bool()); val uartTx = Output(Bool())
        val gmiiRxData = Input(UInt(8.W)); val gmiiRxValid = Input(Bool()); val gmiiRxError = Input(Bool())
        val gmiiTxData = Output(UInt(8.W)); val gmiiTxEnable = Output(Bool()); val gmiiTxError = Output(Bool())
        val linkUp = Input(Bool()); val mdc = Output(Bool()); val mdioIn = Input(Bool())
        val triSpeedRgmii = new soc.ip.ethernet.TriSpeedRgmiiPortV1
        val mdioOut = Output(Bool()); val mdioOe = Output(Bool())
        val jtagDmi = Flipped(new DebugDmiPort(7)); val jtagLinkUp = Input(Bool())
        val maintenance = Flipped(Decoupled(new CommonTileMaintenanceCommand(profile.boundary)))
        val maintenanceStatus = Output(Valid(new CommonTileMaintenanceStatus(profile.boundary)))
        val retire = Output(Vec(2, Valid(new CommonRetireTrace)))
        val trap = Output(Valid(new Bundle { val pc = UInt(64.W); val cause = UInt(64.W) }))
        val cpuCycles = Output(UInt(64.W)); val instructions = Output(UInt(64.W))
        val fabricCycles = Output(UInt(64.W)); val timeSnapshot = Output(UInt(64.W))
        val cpuLinkReady = Output(Bool()); val fabricLinkReady = Output(Bool())
        val cpuTransportEmpty = Output(Bool()); val fabricTransportEmpty = Output(Bool())
        val maintenancePending = Output(Bool()); val homeDrained = Output(Bool())
        val program = if (programmable) Some(Input(Valid(new Bundle {
            val index = UInt(log2Ceil(CommonPlatformAbi.romWords).W); val data = UInt(32.W)
        }))) else None
    })
    private val fabricRelease = Module(new CdcResetRelease)
    fabricRelease.clockIn := fabricClock; fabricRelease.asyncReset := commonColdReset
    private val started = withClockAndReset(fabricClock, fabricRelease.resetOut) {
        val admitted = RegInit(false.B)
        when(io.bootEnable && io.ddrReady) { admitted := true.B }
        when(admitted) { assert(io.ddrReady, "DDR readiness lost: platform requires a common cold reset") }
        admitted
    }
    // A startup-only extension of reset. 'started' never falls except on common
    // cold reset, so this cannot become a one-sided warm-reset mechanism.
    private val startupReset = (commonColdReset.asBool || !started).asAsyncReset
    private val cpuRelease = Module(new CdcResetRelease)
    cpuRelease.clockIn := cpuClock; cpuRelease.asyncReset := startupReset
    val crossing = Module(new CommonCpuClockBoundary(profile.boundary, depth = 16))
    crossing.cpuClock := cpuClock; crossing.fabricClock := fabricClock
    crossing.commonColdReset := startupReset

    // Exactly one fabric and one managed peripheral bank, OUTSIDE the CPU choice.
    val fabric = withClockAndReset(fabricClock, fabricRelease.resetOut) {
        Module(new CommonMachineFabric(boundary = profile.boundary, fpga = profile.fpga,
            features = profile.features, ramBytes = profile.fpga.ddrBytes, externalDdr = true,
            romFiles = romFiles, programmable = programmable, vivadoMemories = vivadoMemories))
    }
    fabric.io.tile <> crossing.fabric
    fabric.io.transportCpuEmptySynchronized := crossing.cpuEmptyInFabric
    fabric.io.fabricTransportEmpty := crossing.fabricTransportEmpty
    fabric.io.ddrReady.get := io.ddrReady
    io.ddrAxi <> fabric.io.ddrAxi.get
    fabric.io.timerTick := true.B
    fabric.io.externalMaintenance <> io.maintenance
    io.maintenanceStatus := fabric.io.externalMaintenanceStatus
    fabric.io.jtagDmi.get <> io.jtagDmi
    fabric.io.jtagLinkUp.get := io.jtagLinkUp
    fabric.io.program.foreach(_ := io.program.get)
    fabric.io.uartRx := true.B // actual UART is the shared managed bank below
    val peripherals = Module(new ManagedPeripheralBank(profile.cmu, profile.cpuHz, profile.uartHz,
        profile.uartBaud, hardwareClocks, networkDmaConfig = profile.fpga.network,
        triSpeedEthernet = true, triSpeedTxFrameSlots = 2,
        sourceClockHz = profile.fabricHz, rateDomains = Some(Seq(
            ClockRateParams(), ClockRateParams(maximumHz = 150000000L)))))
    peripherals.sourceClock := fabricClock; peripherals.alwaysOnClock := alwaysOnClock
    peripherals.rawUartClock := rawUartClock; peripherals.rawTxClock := rawTxClock
    peripherals.rawRxClock := rawRxClock; peripherals.commonReset := commonColdReset
    // Production CMU extension is discoverable, but no clock backend or real
    // CPU/fabric quiesce endpoint is connected yet. Explicit absence rejects
    // every rate write; it must not turn a test ACK into a live clock command.
    peripherals.rateEndpoints.get.foreach { endpoint =>
        endpoint.present := false.B
        endpoint.drainAcks := 0.U
        endpoint.gateClosed := false.B; endpoint.gateOpen := false.B
        endpoint.locked := false.B; endpoint.resumed := false.B
        endpoint.program.ready := false.B
        endpoint.result.valid := false.B
        endpoint.result.bits := 0.U.asTypeOf(endpoint.result.bits)
    }
    peripherals.cmuRegisters <> fabric.io.clockManagementRegisters.get
    peripherals.uartRegisters <> fabric.io.externalUartRegisters.get
    peripherals.gmacRegisters <> fabric.io.ethernetRegisters.get
    peripherals.streams <> fabric.io.ethernetStreams.get
    fabric.io.externalUartIrq.get := peripherals.uartIrq
    fabric.io.sources := io.sources | (peripherals.gmacIrq.asUInt << CommonPlatformAbi.interruptBit(5)) |
        (peripherals.cmuIrq.asUInt << CommonPlatformAbi.interruptBit(7))
    peripherals.uartRx := io.uartRx; io.uartTx := peripherals.uartTx
    peripherals.gmiiRxData := io.gmiiRxData; peripherals.gmiiRxValid := io.gmiiRxValid
    peripherals.gmiiRxError := io.gmiiRxError; peripherals.linkUp := io.linkUp
    peripherals.triSpeedRgmii.get <> io.triSpeedRgmii
    io.gmiiTxData := peripherals.gmiiTxData; io.gmiiTxEnable := peripherals.gmiiTxEnable
    io.gmiiTxError := peripherals.gmiiTxError; io.mdc := peripherals.mdc
    peripherals.mdioIn := io.mdioIn; io.mdioOut := peripherals.mdioOut; io.mdioOe := peripherals.mdioOe

    io.retire := 0.U.asTypeOf(io.retire)
    io.trap := 0.U.asTypeOf(io.trap)
    if (profile.kind == "i1") {
        val cpu = withClockAndReset(cpuClock, cpuRelease.resetOut) {
            Module(new CommonI1CpuTile(profile.i1, profile.boundary))
        }
        crossing.cpu <> cpu.io.bus
        io.retire(0).valid := cpu.io.retire.valid && !cpu.io.retire.bits.trap
        io.retire(0).bits.pc := cpu.io.retire.bits.pc
        io.retire(0).bits.instruction := cpu.io.retire.bits.instruction
        io.retire(0).bits.nextPc := cpu.io.retire.bits.nextPc
        io.retire(0).bits.rd := cpu.io.retire.bits.rd
        io.retire(0).bits.writesRd := cpu.io.retire.bits.writesRd
        io.retire(0).bits.data := cpu.io.retire.bits.data
        io.trap.valid := cpu.io.trapTaken; io.trap.bits.pc := cpu.io.trapPc
        io.trap.bits.cause := cpu.io.trapCause
        io.cpuCycles := cpu.io.cycles; io.instructions := cpu.io.instructions
    } else {
        val cpu = withClockAndReset(cpuClock, cpuRelease.resetOut) {
            Module(new CommonA1CpuTile(profile.fpga, profile.boundary))
        }
        crossing.cpu <> cpu.io.bus
        cpu.io.hold := false.B; cpu.io.inspectRegister := 0.U
        for (i <- 0 until 2) {
            io.retire(i).valid := cpu.io.commit(i).valid
            io.retire(i).bits.pc := cpu.io.commit(i).bits.pc
            io.retire(i).bits.instruction := cpu.io.commit(i).bits.instruction
            io.retire(i).bits.nextPc := cpu.io.commit(i).bits.nextPc
            io.retire(i).bits.rd := cpu.io.commit(i).bits.rd
            io.retire(i).bits.writesRd := cpu.io.commit(i).bits.writesRd
            io.retire(i).bits.data := cpu.io.commit(i).bits.data
        }
        io.trap.valid := cpu.io.trap.valid; io.trap.bits.pc := cpu.io.trap.bits.pc
        io.trap.bits.cause := cpu.io.trap.bits.cause
        val counters = withClockAndReset(cpuClock, cpuRelease.resetOut) {
            val cycles = RegInit(0.U(64.W)); val retired = RegInit(0.U(64.W))
            cycles := cycles + 1.U; retired := retired + PopCount(cpu.io.commit.map(_.valid))
            (cycles, retired)
        }
        io.cpuCycles := counters._1; io.instructions := counters._2
    }
    io.fabricCycles := withClockAndReset(fabricClock, fabricRelease.resetOut) {
        val cycles = RegInit(0.U(64.W)); cycles := cycles + 1.U; cycles
    }
    io.timeSnapshot := crossing.cpu.timeSnapshot
    io.cpuLinkReady := crossing.cpuLinkReady; io.fabricLinkReady := crossing.fabricLinkReady
    io.cpuTransportEmpty := crossing.cpuTransportEmpty; io.fabricTransportEmpty := crossing.fabricTransportEmpty
    io.maintenancePending := fabric.io.maintenancePending; io.homeDrained := fabric.io.homeDrained
}
