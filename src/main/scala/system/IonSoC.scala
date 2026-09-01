package soc

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import difftest._

import soc.config.Config
import soc.config.InterruptControllerKind
import soc.config.SoCFeatures
import soc.core._
import soc.device.BROM
import soc.device.TLROM
import soc.device.UartTx
import soc.device.CLINT
import soc.debug.DebugModule
import soc.debug.JtagTap
import soc.device.interrupt.PLIC
import soc.bus.tilelink.TLXbar
import soc.bus.tilelink.TLParams
import soc.bus.tilelink.TLRAM
import soc.bus.tilelink.TLBundle
import soc.isa.Extension
import soc.core.csr.CsrStateSnapshot

class IonSoC(
    features: SoCFeatures = Config.features,
    enabledExt: Set[Extension.Value] = Config.enabledExt,
    sramInitFile: String = "",
    difftestStimulus: Boolean = false,
    useDifftestMemory: Boolean = false
) extends Module {
    private val tlParams = TLParams()
    private val dbusParams = tlParams.copy(sourceBits = tlParams.sourceBits + 2)
    private val debugBusMasters = 2 // core DBus plus Debug Module SBA.
    private val deviceParams = dbusParams.copy(sourceBits = dbusParams.sourceBits + log2Ceil(debugBusMasters))
    private val mmioRegions = Config.mmioRegionsFor(features)
    private val slaveCount = mmioRegions.length

    val io = IO(new Bundle {
        val debug     = new soc.debug.DebugIO
        val uart_rx_valid = Input(Bool())
        val uart_rx_byte  = Input(UInt(8.W))
        val uart_tx   = Output(Bool())
        val uart_byte = Output(UInt(8.W))
        val ext_irq_sources = Input(Vec(Config.plicSources + 1, Bool()))
        val jtag_tms = Input(Bool())
        val jtag_tck = Input(Bool())
        val jtag_tdi = Input(Bool())
        val jtag_tdo = Output(Bool())
        val debug_arch_event_valid = Output(Bool())
        val debug_arch_event_interrupt = Output(Bool())
        val debug_arch_event_cause = Output(UInt(Config.XLEN.W))
        val debug_arch_event_pc = Output(UInt(Config.XLEN.W))
        val debug_arch_event_instr = Output(UInt(32.W))
        val debug_arch_event_tval = Output(UInt(Config.XLEN.W))
        val debug_gpr_snapshot = Output(Vec(32, UInt(Config.XLEN.W)))
        val debug_csr_snapshot = Output(new CsrStateSnapshot(Config.XLEN))
    })

    val core  = Module(new Core(Config.XLEN, hartID = 0, features, enabledExt))
    val brom  = Module(new BROM(Config.XLEN, Config.romDepth, Config.romInit))
    val sram  = Module(
        new TLRAM(deviceParams, features.sramSizeBytes, features.sramBase, sramInitFile, useDifftestMemory)
    )
    val debugModule = Module(new DebugModule(deviceParams, dbusParams))
    val tlrom = Module(new TLROM(deviceParams))
    val uart  = if (features.uart) Some(Module(new UartTx(deviceParams))) else None
    val clint = if (features.clint) Some(Module(new CLINT(deviceParams))) else None
    val plic  = if (features.interruptController == InterruptControllerKind.PLIC) Some(Module(new PLIC(deviceParams, Config.plicSources))) else None
    val jtag  = Module(new JtagTap(drLen = Config.XLEN))

    val TLCrossbar = Module(new TLXbar(
        dbusParams,
        debugBusMasters,
        slaveCount,
        Config.addrMapFor(features),
        Config.releaseSupportFor(features)
    ))

    brom.io.fetch_en := core.io.fetch_en
    brom.io.addr     := core.io.pc
    core.io.instr    := brom.io.instr
    core.io.msip     := clint.map(_.io.msip).getOrElse(false.B)
    core.io.mtip     := clint.map(_.io.mtip).getOrElse(false.B)
    core.io.meip     := plic.map(_.io.meip).getOrElse(false.B)
    core.io.ssip     := false.B
    core.io.stip     := false.B
    core.io.seip     := plic.map(_.io.seip).getOrElse(false.B)
    core.io.debug_haltreq := debugModule.io.haltreq
    core.io.debug_resumereq := debugModule.io.resumereq
    core.io.debug_gpr_addr := debugModule.io.gpr_addr
    core.io.debug_gpr_write := debugModule.io.gpr_write
    core.io.debug_gpr_wdata := debugModule.io.gpr_wdata
    core.io.debug_csr_addr := debugModule.io.csr_addr
    core.io.debug_csr_write := debugModule.io.csr_write
    core.io.debug_csr_wdata := debugModule.io.csr_wdata

    jtag.io.jtag.tms := io.jtag_tms
    jtag.io.jtag.tck := io.jtag_tck
    jtag.io.jtag.tdi := io.jtag_tdi
    io.jtag_tdo := jtag.io.jtag.tdo
    jtag.io.dr_in := Cat(0.U(30.W), debugModule.io.dmi_rdata, debugModule.io.dmi_resp_op)
    debugModule.io.dmi_valid := RegNext(jtag.io.update_dr, false.B)
    debugModule.io.dmi_write := jtag.io.dr_out(1, 0) === 2.U
    debugModule.io.dmi_addr  := jtag.io.dr_out(40, 34)
    debugModule.io.dmi_wdata := jtag.io.dr_out(33, 2)
    debugModule.io.hart_halted := core.io.debug_halted
    debugModule.io.hart_pc := core.io.pc
    debugModule.io.gpr_rdata := core.io.debug_gpr_rdata
    debugModule.io.csr_rdata := core.io.debug_csr_rdata
    debugModule.io.csr_valid := core.io.debug_csr_valid
    debugModule.io.csr_writable := core.io.debug_csr_writable
    debugModule.io.cache <> core.io.debug_cache

    val effectiveExtIrqSources = Wire(Vec(Config.plicSources + 1, Bool()))
    effectiveExtIrqSources := io.ext_irq_sources
    val effectiveUartRxValid = WireDefault(io.uart_rx_valid)
    val effectiveUartRxByte = WireDefault(io.uart_rx_byte)
    if (difftestStimulus) {
        if (Config.plicSources >= 2) {
            effectiveExtIrqSources(2) := true.B
        }
        val uartInjected = RegInit(false.B)
        effectiveUartRxValid := !uartInjected
        effectiveUartRxByte := "h5a".U
        when(!uartInjected) {
            uartInjected := true.B
        }
    }

    uart.foreach { device =>
        device.io.rx_valid := effectiveUartRxValid
        device.io.rx_byte  := effectiveUartRxByte
    }

    plic.foreach { device =>
        device.io.sources := effectiveExtIrqSources
        uart.foreach { uartDevice =>
            device.io.sources(Config.UartPlicSource) := effectiveExtIrqSources(Config.UartPlicSource) || uartDevice.io.irq
        }
    }

    TLCrossbar.io.masters(0) <> core.io.DBus
    TLCrossbar.io.masters(1) <> debugModule.io.sba

    private var slaveIndex = 0
    private def connectSlave(tl: TLBundle): Unit = {
        TLCrossbar.io.slaves(slaveIndex) <> tl
        slaveIndex += 1
    }

    connectSlave(debugModule.io.tl)
    connectSlave(tlrom.io.tl)
    connectSlave(sram.io.tl)
    uart.foreach(device => connectSlave(device.io.tl))
    clint.foreach(device => connectSlave(device.io.tl))
    plic.foreach(device => connectSlave(device.io.tl))
    require(slaveIndex == slaveCount, s"connected $slaveIndex slaves, expected $slaveCount")

    core.io.IBus <> DontCare
    dontTouch(sram.io)
    dontTouch(jtag.io)
    uart.foreach(device => dontTouch(device.io))
    clint.foreach(device => dontTouch(device.io))
    plic.foreach(device => dontTouch(device.io))

    // Debug ports
    io.debug.pc    := core.io.pc
    io.debug.instr := core.io.debug_instr
    io.debug.retire := core.io.debug_retire
    io.debug.stall := core.io.debug_stall
    io.debug.ifetchStall := core.io.debug_ifetch_stall
    io.debug.frontendStarved := core.io.debug_frontend_starved
    io.debug.frontendQueueFull := core.io.debug_frontend_queue_full
    io.debug.frontendQueueEmpty := core.io.debug_frontend_queue_empty
    io.debug.lsuStall := core.io.debug_lsu_stall
    io.debug.lsuLoadStall := core.io.debug_lsu_load_stall
    io.debug.lsuStoreStall := core.io.debug_lsu_store_stall
    io.debug.lsuMmioStall := core.io.debug_lsu_mmio_stall
    io.debug.lsuAtomicStall := core.io.debug_lsu_atomic_stall
    io.debug.lsuFenceStall := core.io.debug_lsu_fence_stall
    io.debug.fenceIActive := core.io.debug_fence_i_active
    io.debug.branchValid := core.io.debug_branch_valid
    io.debug.branchTaken := core.io.debug_branch_taken
    io.debug.branchRedirect := core.io.debug_branch_redirect
    io.debug.branchPredTaken := core.io.debug_branch_pred_taken
    io.debug.branchPredCorrect := core.io.debug_branch_pred_correct
    io.debug.commitPc := core.io.debug_commit_pc
    io.debug.commitInstr := core.io.debug_commit_instr
    io.debug.commitInstrLen := core.io.debug_commit_instr_len
    io.debug.commitWen := core.io.debug_commit_wen
    io.debug.commitWdest := core.io.debug_commit_wdest
    io.debug.commitWdata := core.io.debug_commit_wdata
    io.debug.commitSkip := core.io.debug_commit_skip
    io.debug_arch_event_valid := core.io.debug_arch_event_valid
    io.debug_arch_event_interrupt := core.io.debug_arch_event_interrupt
    io.debug_arch_event_cause := core.io.debug_arch_event_cause
    io.debug_arch_event_pc := core.io.debug_arch_event_pc
    io.debug_arch_event_instr := core.io.debug_arch_event_instr
    io.debug_arch_event_tval := core.io.debug_arch_event_tval
    io.debug_gpr_snapshot := core.io.debug_gpr_snapshot
    io.debug_csr_snapshot := core.io.debug_csr_snapshot

    // UART TX outputs
    io.uart_tx   := uart.map(_.io.tx_valid).getOrElse(false.B)
    io.uart_byte := uart.map(_.io.tx_byte).getOrElse(0.U)
}

class IonSoCDifftest(
    features: SoCFeatures = Config.features,
    enabledExt: Set[Extension.Value] = Config.enabledExt,
    injectTestStimulus: Boolean = true,
    exitOnBareMetalSentinel: Boolean = true
) extends IonSoC(
      features,
      enabledExt,
      difftestStimulus = injectTestStimulus,
      useDifftestMemory = true
    )
    with HasDiffTestInterfaces {
    override def cpuName: Option[String] = Some("IonSoC")

    private val archEvent = DifftestModule(new DiffArchEvent, dontCare = true)
    archEvent.coreid := 0.U
    archEvent.valid := io.debug_arch_event_valid
    archEvent.interrupt := Mux(io.debug_arch_event_interrupt, io.debug_arch_event_cause(31, 0), 0.U)
    archEvent.exception := Mux(io.debug_arch_event_interrupt, 0.U, io.debug_arch_event_cause(31, 0))
    archEvent.exceptionPC := io.debug_arch_event_pc
    archEvent.exceptionInst := io.debug_arch_event_instr
    archEvent.hasNMI := false.B
    archEvent.virtualInterruptIsHvictlInject := false.B
    archEvent.irToHS := false.B
    archEvent.irToVS := false.B

    private val commit = DifftestModule(new DiffInstrCommit(32), dontCare = true)
    private val committedCsrAddr = io.debug.commitInstr(31, 20)
    private val committedCsrOp = io.debug.commitInstr(6, 0) === "b1110011".U && io.debug.commitInstr(14, 12) =/= 0.U
    // NEMU intentionally models HPM/event counters as read-only zero, while
    // IonSoC implements writable counters. Counter values are also timing
    // dependent, so synchronize these CSR instructions just like MMIO reads.
    private val implementationDefinedCounterCsr =
        (committedCsrAddr >= "hB00".U && committedCsrAddr <= "hB1F".U) ||
            (committedCsrAddr >= "hC00".U && committedCsrAddr <= "hC1F".U) ||
            committedCsrAddr === "h320".U ||
            (committedCsrAddr >= "h323".U && committedCsrAddr <= "h33F".U)
    commit.coreid := 0.U
    commit.index := 0.U
    commit.valid := io.debug.retire
    commit.skip := io.debug.commitSkip || (committedCsrOp && implementationDefinedCounterCsr)
    commit.isRVC := io.debug.commitInstrLen === 2.U
    commit.rfwen := io.debug.commitWen
    commit.fpwen := false.B
    commit.vecwen := false.B
    commit.v0wen := false.B
    commit.wpdest := io.debug.commitWdest
    commit.wdest := io.debug.commitWdest
    commit.otherwpdest.foreach(_ := 0.U)
    commit.pc := io.debug.commitPc
    commit.instr := io.debug.commitInstr
    commit.robIdx := 0.U
    commit.lqIdx := 0.U
    commit.sqIdx := 0.U
    commit.isLoad := false.B
    commit.isStore := false.B
    commit.nFused := 0.U
    commit.special := 0.U

    // The official DiffTest emu uses TrapEvent counters for max-cycle/max-
    // instruction exits and stuck detection. Keep them in hardware so
    // difftest runs can terminate even before the payload reaches a trap.
    private val difftestCycleCnt = RegInit(0.U(64.W))
    private val difftestInstrCnt = RegInit(0.U(64.W))
    difftestCycleCnt := difftestCycleCnt + 1.U
    when(io.debug.retire) {
        difftestInstrCnt := difftestInstrCnt + 1.U
    }

    private val trap = DifftestModule(new DiffTrapEvent, dontCare = true)
    private val difftestExit = if (exitOnBareMetalSentinel) {
        val armed = RegInit(false.B)
        val exit = RegInit(false.B)
        when(io.debug.retire && io.debug.commitWen && io.debug.commitWdest === 17.U && io.debug.commitWdata === 93.U) {
            armed := true.B
        }.elsewhen(armed && io.debug.retire) {
            exit := true.B
        }
        exit
    } else {
        false.B
    }
    trap.coreid := 0.U
    trap.hasTrap := difftestExit
    trap.cycleCnt := difftestCycleCnt
    trap.instrCnt := difftestInstrCnt
    // DiffTest uses hasWFI as a generic "legal no-retire window" marker. A
    // dirty-cache fence.i can exceed its fixed 1000-cycle stuck threshold.
    trap.hasWFI := io.debug.fenceIActive
    trap.code := io.debug_gpr_snapshot(10)
    trap.pc := io.debug.commitPc

    private val csr = DifftestModule(new DiffCSRState, dontCare = true)
    csr.coreid := 0.U
    csr.privilegeMode := io.debug_csr_snapshot.privilegeMode
    csr.mstatus := io.debug_csr_snapshot.mstatus
    csr.sstatus := io.debug_csr_snapshot.sstatus
    csr.mepc := io.debug_csr_snapshot.mepc
    csr.sepc := io.debug_csr_snapshot.sepc
    csr.mtval := io.debug_csr_snapshot.mtval
    csr.stval := io.debug_csr_snapshot.stval
    csr.mtvec := io.debug_csr_snapshot.mtvec
    csr.stvec := io.debug_csr_snapshot.stvec
    csr.mcause := io.debug_csr_snapshot.mcause
    csr.scause := io.debug_csr_snapshot.scause
    csr.satp := io.debug_csr_snapshot.satp
    // Device MMIO is skipped in DiffTest, so the REF does not model CLINT/PLIC
    // pending bits. ArchEvent injects the actual trap; keep CSR comparison
    // focused on architectural trap state instead of local device side effects.
    csr.mip := 0.U
    csr.mie := io.debug_csr_snapshot.mie
    csr.mscratch := io.debug_csr_snapshot.mscratch
    csr.sscratch := io.debug_csr_snapshot.sscratch
    csr.mideleg := io.debug_csr_snapshot.mideleg
    csr.medeleg := io.debug_csr_snapshot.medeleg

    private val gpr = DifftestModule(new DiffPhyIntRegState(32), dontCare = true)
    gpr.coreid := 0.U
    gpr.value := io.debug_gpr_snapshot

    override def connectTopIOs(difftest: DifftestTopIO): Unit = {
        difftest.uart.out.valid := io.uart_tx
        difftest.uart.out.ch := io.uart_byte
    }
}
