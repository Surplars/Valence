package soc.core.inorder

import chisel3._
import soc.ip.axi.Axi4MemoryPort
import soc.ip.bus.{CdcResetRelease, CdcLevel}
import soc.ip.clock.{ClockResource, CmuParams, ClockManagementBoundary}
import soc.ip.uart.ManagedUart

/** Temporary parameterized no-MAC board composition. CPU300, AON/UART50 and
  * DDR UI250 remain independent. No Ethernet/DMA/PHY instance is tied idle.
  * The normal network shell and all shared/OoO IP sources stay unchanged.
  */
class I1PeripheralFpgaShell(p: FiveStageSocConfig, jtagChain: Int = 0,
    hardwareClocks: Boolean = true, jtagScanBits: Int = 64) extends RawModule {
    I1BscanRamTransport.validateScanBits(jtagScanBits)
    require(p.managedPeripherals && !p.withNetwork && p.core.coherentCaches)
    require(if (p.withJtagLoader) Set(2, 3, 4).contains(jtagChain) else jtagChain == 0)
    val io = IO(new Bundle {
        val clockIn = Input(Clock()); val alwaysOnClock = Input(Clock()); val uartClockIn = Input(Clock())
        val resetN = Input(Bool()); val clockLocked = Input(Bool()); val ddrReady = Input(Bool())
        val uartRx = Input(Bool()); val uartTx = Output(Bool()); val externalIrq = Input(Bool())
        val ddrAxi = new Axi4MemoryPort(32, 4)
        val resetHeld = Output(Bool()); val resetFault = Output(Bool())
        val clockEnabled = Output(UInt(7.W))
    })
    val commonReset = (!io.resetN).asAsyncReset
    val release = Module(new CdcResetRelease)
    release.clockIn := io.clockIn; release.asyncReset := commonReset
    val soc = withClockAndReset(io.clockIn, release.resetOut) { Module(new FiveStageSoc(p)) }
    val config = CmuParams(50000000, Seq(
        ClockResource("AON", 50000000), ClockResource("CPU", p.clockHz),
        ClockResource("DDR", 250000000), ClockResource("UART", 50000000, canGate = true),
        ClockResource("ETHREF", 0, present = false),
        ClockResource("MACTX", 0, present = false), ClockResource("MACRX", 0, present = false)))
    val bank = Module(new I1UartClockBank(config, p.clockHz, p.uartBaud, hardwareClocks))
    bank.sourceClock := io.clockIn; bank.alwaysOnClock := io.alwaysOnClock
    bank.rawUartClock := io.uartClockIn; bank.commonReset := commonReset
    bank.cmuRegisters <> soc.io.cmuControl.get; bank.uartRegisters <> soc.io.externalUart.get
    bank.uartRx := io.uartRx; io.uartTx := bank.uartTx
    soc.io.externalUartIrq.get := bank.uartIrq; soc.io.cmuIrq.get := bank.cmuIrq
    io.clockEnabled := bank.enabled
    soc.io.uartRx := true.B
    val irq = Module(new CdcLevel)
    irq.clockIn := io.clockIn; irq.resetIn := release.resetOut; irq.levelIn := io.externalIrq
    soc.io.externalIrq := irq.levelOut
    soc.io.clockLocked := io.clockLocked; soc.io.ddrReady := io.ddrReady
    io.ddrAxi <> soc.io.ddrAxi; io.resetHeld := soc.io.resetHeld; io.resetFault := soc.io.resetFault
    if (p.withJtagLoader) {
        val transport = Module(new I1BscanRamTransport(jtagChain, p.core.fpgaTimingCuts, jtagScanBits))
        transport.io.debug_clk := io.clockIn; transport.io.debug_por_n := !release.resetOut.asBool
        soc.io.jtagLinkUp := transport.io.dmi_reset_n
        soc.io.jtagDmi.request.valid := transport.io.dmi_req_valid
        soc.io.jtagDmi.request.bits.op := transport.io.dmi_req_op
        soc.io.jtagDmi.request.bits.address := transport.io.dmi_req_address
        soc.io.jtagDmi.request.bits.data := transport.io.dmi_req_data
        transport.io.dmi_req_ready := soc.io.jtagDmi.request.ready
        transport.io.dmi_rsp_valid := soc.io.jtagDmi.response.valid
        transport.io.dmi_rsp_status := soc.io.jtagDmi.response.bits.status
        transport.io.dmi_rsp_data := soc.io.jtagDmi.response.bits.data
        soc.io.jtagDmi.response.ready := transport.io.dmi_rsp_ready
    } else {
        soc.io.jtagLinkUp := false.B; soc.io.jtagDmi.request.valid := false.B
        soc.io.jtagDmi.request.bits := 0.U.asTypeOf(soc.io.jtagDmi.request.bits)
        soc.io.jtagDmi.response.ready := false.B
    }
}

class I1UartClockBank(config: CmuParams, cpuHz: Int, baud: Int, hardwareClocks: Boolean) extends RawModule {
    val sourceClock = IO(Input(Clock())); val alwaysOnClock = IO(Input(Clock()))
    val rawUartClock = IO(Input(Clock())); val commonReset = IO(Input(AsyncReset()))
    val cmuRegisters = IO(Flipped(new soc.ip.bus.RegisterPort))
    val uartRegisters = IO(Flipped(new soc.ip.bus.RegisterPort))
    val uartRx = IO(Input(Bool())); val uartTx = IO(Output(Bool()))
    val uartIrq = IO(Output(Bool())); val cmuIrq = IO(Output(Bool()))
    val enabled = IO(Output(UInt(7.W)))
    val cmu = Module(new ClockManagementBoundary(config))
    cmu.sourceClock := sourceClock; cmu.alwaysOnClock := alwaysOnClock; cmu.commonReset := commonReset
    cmu.registers <> cmuRegisters; cmuIrq := cmu.irq
    for (n <- Seq(0, 1, 2, 4, 5, 6)) {
        cmu.resources(n).ack := false.B; cmu.resources(n).wake := false.B
    }
    val uart = Module(new ManagedUart(cpuHz, 50000000, config.alwaysOnHz, baud, hardwareClocks,
        balancedRawClock = hardwareClocks))
    uart.sourceClock := sourceClock; uart.rawClock := rawUartClock; uart.commonReset := commonReset
    uart.registers <> uartRegisters; uart.control <> cmu.resources(3)
    uart.rx := uartRx; uartTx := uart.tx; uartIrq := uart.irq
    enabled := VecInit(cmu.resources.map(_.clockEnable)).asUInt
}
