package soc.core.inorder

import chisel3._
import chisel3.util._
import soc.ip.axi.Axi4MemoryPort
import soc.ip.bus.{CdcResetRelease, CdcLevel}
import soc.ip.clock.{ClockResource, CmuParams, ManagedPeripheralBank}
import soc.ip.dma.{EthernetPacketDma, NetworkDmaConfig}
import soc.ip.ethernet.TriSpeedRgmiiPortV1

/** Complete CPU-independent managed bank composition. Clock generation,
  * DDR AXI CDC/MIG and RGMII IOB primitives remain the board wrapper's job.
  * CPU target300MHz does not force UART/AON/MAC to that frequency.
  */
class I1NetworkFpgaShell(p: FiveStageSocConfig, jtagChain: Int = 0,
    hardwareClocks: Boolean = true, network: NetworkDmaConfig = NetworkDmaConfig.Default,
    aonHz: Int = 50000000, uartHz: Int = 50000000, ddrUiHz: Int = 250000000,
    jtagScanBits: Int = 64) extends RawModule {
    I1BscanRamTransport.validateScanBits(jtagScanBits)
    require(p.withNetwork && p.managedPeripherals && p.core.coherentCaches)
    require(if (p.withJtagLoader) Set(2, 3, 4).contains(jtagChain) else jtagChain == 0)
    val io = IO(new Bundle {
        val clockIn = Input(Clock()); val alwaysOnClock = Input(Clock()); val uartClockIn = Input(Clock())
        val macTxClock = Input(Clock()); val macRxClock = Input(Clock())
        val resetN = Input(Bool()); val clockLocked = Input(Bool()); val ddrReady = Input(Bool())
        val uartRx = Input(Bool()); val uartTx = Output(Bool()); val externalIrq = Input(Bool())
        val ddrAxi = new Axi4MemoryPort(32, 4)
        val rgmii = new TriSpeedRgmiiPortV1
        val mdc = Output(Bool()); val mdioIn = Input(Bool())
        val mdioOut = Output(Bool()); val mdioOe = Output(Bool())
        val resetHeld = Output(Bool()); val resetFault = Output(Bool())
        val clockEnabled = Output(UInt(7.W))
    })
    // The caller must coordinate this POR with AXI CDC/MIG. Clock loss is
    // reported by Startup; do not unilaterally hot-reset accepted DMA owners.
    val commonReset = (!io.resetN).asAsyncReset
    val release = Module(new CdcResetRelease)
    release.clockIn := io.clockIn; release.asyncReset := commonReset
    val soc = withClockAndReset(io.clockIn, release.resetOut) { Module(new FiveStageSoc(p)) }
    val cmu = CmuParams(aonHz, Seq(
        ClockResource("AON", aonHz),
        ClockResource("CPU", p.clockHz),
        ClockResource("DDR", ddrUiHz),
        ClockResource("UART", uartHz, canGate = true),
        ClockResource("ETHREF", 125000000),
        ClockResource("MACTX", 125000000, canGate = true, parent = 4),
        ClockResource("MACRX", 125000000, canGate = true, parent = 4)))
    val bank = Module(new ManagedPeripheralBank(cmu, p.clockHz, uartHz, p.uartBaud, hardwareClocks,
        network, triSpeedEthernet = true, balancedRawClocks = hardwareClocks && p.core.coherentControlCuts))
    bank.sourceClock := io.clockIn; bank.alwaysOnClock := io.alwaysOnClock
    bank.rawUartClock := io.uartClockIn; bank.rawTxClock := io.macTxClock; bank.rawRxClock := io.macRxClock
    bank.commonReset := commonReset
    bank.cmuRegisters <> soc.io.cmuControl.get
    bank.uartRegisters <> soc.io.externalUart.get
    bank.gmacRegisters <> soc.io.gmacControl.get
    bank.uartRx := io.uartRx; io.uartTx := bank.uartTx
    bank.triSpeedRgmii.get <> io.rgmii
    bank.gmiiRxData := 0.U; bank.gmiiRxValid := false.B; bank.gmiiRxError := false.B
    bank.linkUp := false.B
    bank.mdioIn := io.mdioIn
    io.mdc := bank.mdc; io.mdioOut := bank.mdioOut; io.mdioOe := bank.mdioOe
    io.clockEnabled := bank.enabled
    val dma = withClockAndReset(io.clockIn, release.resetOut) {
        Module(new EthernetPacketDma(p.networkDmaBase, p.ddrBase, p.ddrBytes,
            network.maxFrameBytes, network.postedRxSlots, network.memoryCredits, network.postedTxSlots,
            boundedDescriptorChecks = p.core.coherentControlCuts))
    }
    dma.io.control <> soc.io.networkDmaControl.get
    soc.io.networkMemory.get <> dma.io.memory
    bank.streams.txData <> dma.io.txData; bank.streams.txControl <> dma.io.txControl
    dma.io.rxData <> bank.streams.rxData; dma.io.rxStatus <> bank.streams.rxStatus
    soc.io.networkIrqs.get := Cat(bank.cmuIrq, dma.io.irq, bank.gmacIrq)
    soc.io.externalUartIrq.get := bank.uartIrq
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
