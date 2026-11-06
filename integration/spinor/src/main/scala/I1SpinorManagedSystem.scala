package soc.integration.spinor

import chisel3._
import chisel3.util._
import soc.core.inorder._
import soc.bus.tilelink.TLParams
import soc.ip.axi.Axi4MemoryPort
import soc.ip.bus.{CdcLevel, CdcMailbox, CdcResetRelease, PeripheralQuiesceAck}
import soc.ip.clock.{ClockManagementUnit, ClockResource, CmuParams, ManagedClockBuffer}
import soc.ip.tilelink.TileLinkClockDomainBoundary

/** Three independent clocks. CPU/VPU inputs are the managed clock outputs;
  * systemClock is always on. The FPGA wrapper below supplies real BUFGCE gates.
  * Common cold reset also starts a new external AXI memory transaction epoch.
  */
class I1SpinorManagedSystem(p: FiveStageConfig, systemHz: Int = 300000000,
    cpuHz: Long = 300000000L, vpuHz: Long = 300000000L) extends RawModule {
    require(p.spinor && p.xlen == 64 && p.fpgaTimingCuts && !p.coherentCaches)
    val cpuClock = IO(Input(Clock())); val vpuClock = IO(Input(Clock()))
    val systemClock = IO(Input(Clock())); val commonColdReset = IO(Input(AsyncReset()))
    val io = IO(new Bundle {
        val memory = new Axi4MemoryPort(32, 4) // system clock, DDR-window offsets
        val memoryReady = Input(Bool())
        val uartRx = Input(Bool()); val uartTx = Output(Bool())
        val externalIrq = Input(Bool())
        val wakeCpu = Input(Bool()); val wakeVpu = Input(Bool()) // held wake levels
        val cpuClockEnable = Output(Bool()); val vpuClockEnable = Output(Bool())
        val cpuStopAck = Output(Bool()); val vpuStopAck = Output(Bool()) // system clock
        val fabricIdle = Output(Bool()); val protocolError = Output(Bool())
        val retire = Valid(new FiveStageRetire(p)) // CPU clock
    })
    val systemRelease = Module(new CdcResetRelease)
    systemRelease.clockIn := systemClock; systemRelease.asyncReset := commonColdReset
    val cpuRelease = Module(new CdcResetRelease)
    cpuRelease.clockIn := cpuClock; cpuRelease.asyncReset := commonColdReset
    def synchronize(name: String, value: Bool, target: Clock, localReset: AsyncReset): Bool = {
        val crossing = Module(new CdcLevel); crossing.suggestName(name)
        crossing.clockIn := target; crossing.resetIn := localReset; crossing.levelIn := value
        crossing.levelOut
    }
    val soc = FiveStageSocConfig(core = p, ddrBase = p.cacheableBase, ddrBytes = p.cacheableBytes,
        clockHz = systemHz, uartBaud = 460800, withBootRom = false, withJtagLoader = false,
        managedPeripherals = true, fabricTimingCuts = true)
    val fabric = withClockAndReset(systemClock, systemRelease.resetOut) {
        Module(new I1SpinorSystemFabric(soc))
    }
    val cmuConfig = CmuParams(systemHz, Seq(ClockResource("SYSTEM", systemHz),
        ClockResource("CPU", cpuHz, canGate = true, parent = 0),
        ClockResource("VPU", vpuHz, canGate = true, parent = 0)))
    val cmu = withClockAndReset(systemClock, systemRelease.resetOut) {
        Module(new ClockManagementUnit(cmuConfig))
    }
    cmu.io.registers <> fabric.io.cmu
    cmu.io.resources(0).ack := false.B; cmu.io.resources(0).wake := false.B
    fabric.io.cmuIrq := cmu.io.irq
    fabric.io.externalIrq := io.externalIrq; fabric.io.memoryReady := io.memoryReady
    fabric.io.uartRx := io.uartRx; io.uartTx := fabric.io.uartTx
    io.memory <> fabric.io.axi; io.fabricIdle := fabric.io.idle
    io.cpuClockEnable := cmu.io.resources(1).clockEnable
    io.vpuClockEnable := cmu.io.resources(2).clockEnable

    val unit = Module(new I1SpinorDualClockCore(p, managedClocks = true))
    unit.cpuClock := cpuClock; unit.vpuClock := vpuClock; unit.commonColdReset := commonColdReset
    io.retire := unit.io.retire; io.protocolError := unit.io.protocolError
    unit.io.externalIrq := synchronize("machineIrq", fabric.io.machineIrq, cpuClock, cpuRelease.resetOut)
    unit.io.timerIrq := synchronize("timerIrq", fabric.io.timerIrq, cpuClock, cpuRelease.resetOut)
    unit.io.softwareIrq := synchronize("softwareIrq", fabric.io.softwareIrq, cpuClock, cpuRelease.resetOut)
    unit.io.supervisorExternalIrq.foreach(_ :=
        synchronize("supervisorIrq", fabric.io.supervisorIrq, cpuClock, cpuRelease.resetOut))
    cmu.io.resources(1).wake := io.wakeCpu || fabric.io.machineIrq || fabric.io.supervisorIrq ||
        fabric.io.timerIrq || fabric.io.softwareIrq
    cmu.io.resources(2).wake := io.wakeVpu || unit.io.vectorWake.get

    // Register policy admission before crossing: it is a Boolean decode,
    // whereas quiesce/clockEnable/isolate already come from policy registers.
    val cpuAdmission = withClockAndReset(systemClock, systemRelease.resetOut) {
        RegNext(cmu.io.resources(1).allowAdmission, false.B)
    }
    val vpuAdmission = withClockAndReset(systemClock, systemRelease.resetOut) {
        RegNext(cmu.io.resources(2).allowAdmission, false.B)
    }
    val admitCpu = synchronize("cpuAdmission", cpuAdmission, cpuClock, cpuRelease.resetOut)
    val admitVpu = synchronize("vpuAdmission", vpuAdmission, cpuClock, cpuRelease.resetOut)
    unit.io.blockVectorAdmission.get := !admitVpu

    val links = Seq.fill(2)(Module(new TileLinkClockDomainBoundary(
        TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 1, sizeBits = 3), depth = 4, heldResponseStorage = true)))
    val adapters = Seq.fill(2)(withClockAndReset(cpuClock, cpuRelease.resetOut) {
        Module(new FiveStageTileLink(p))
    })
    for (i <- 0 until 2) {
        adapters(i).io.native <> Seq(unit.io.instructionMemory, unit.io.dataMemory)(i)
        links(i).cpuClock := cpuClock; links(i).fabricClock := systemClock
        links(i).commonColdReset := commonColdReset
        links(i).cpu <> adapters(i).io.tl
        fabric.io.clients(i) <> links(i).fabric
    }

    // Time is a coherent held snapshot, not a multi-bit asynchronous sample.
    // Pause new snapshots throughout drain AND isolation so wake ACK cannot
    // fall merely because the always-on source started another transfer.
    val time = Module(new CdcMailbox(64))
    time.sourceClock := systemClock; time.destinationClock := cpuClock
    time.commonReset := commonColdReset
    time.source.valid := !cmu.io.resources(1).quiesce && !cmu.io.resources(1).isolate
    time.source.bits := fabric.io.time; time.destination.ready := true.B
    val cpuTime = withClockAndReset(cpuClock, cpuRelease.resetOut) {
        val value = RegInit(0.U(64.W)); when(time.destination.fire) { value := time.destination.bits }; value
    }
    unit.io.time := cpuTime

    val cpuAgent = Module(new PeripheralQuiesceAck)
    cpuAgent.domainClock := cpuClock; cpuAgent.commonReset := commonColdReset
    cpuAgent.quiesce := cmu.io.resources(1).quiesce
    val vpuAgent = Module(new PeripheralQuiesceAck)
    vpuAgent.domainClock := vpuClock; vpuAgent.commonReset := commonColdReset
    vpuAgent.quiesce := cmu.io.resources(2).quiesce
    val cpuLocalEmpty = unit.io.cpuQuiescent.get && unit.io.cpuTransportIdle &&
        links.map(_.cpuTransportEmpty).reduce(_ && _) && time.destinationIdle && !admitCpu
    cpuAgent.idle := cpuLocalEmpty
    vpuAgent.idle := unit.io.vectorIdle.get && unit.io.vpuTransportIdle
    // Retain precise core stop through waking/isolation. Local ACK can return
    // low after real edges without admitting fresh CPU work before CMU releases it.
    val retainCpuStop = withClockAndReset(cpuClock, cpuRelease.resetOut) {
        val held = RegInit(false.B)
        when(cpuAgent.stopAdmission && cpuLocalEmpty) { held := true.B }
        when(!cpuAgent.stopAdmission && admitCpu) { held := false.B }
        held
    }
    unit.io.quiesceRequest.get := cpuAgent.stopAdmission || retainCpuStop

    val cpuAck = synchronize("cpuAck", cpuAgent.ack, systemClock, systemRelease.resetOut)
    val vpuAck = synchronize("vpuAck", vpuAgent.ack, systemClock, systemRelease.resetOut)
    val cpuSpinorEmpty = synchronize("cpuSpinorEmpty", unit.io.cpuTransportIdle,
        systemClock, systemRelease.resetOut)
    val vpuSpinorEmpty = synchronize("vpuSpinorEmpty", unit.io.vpuTransportIdle,
        systemClock, systemRelease.resetOut)
    val vectorAdmissionClosed = synchronize("vectorAdmissionClosed", !admitVpu,
        systemClock, systemRelease.resetOut)
    val cpuIsStopped = cmu.io.resources(1).isolate && !cmu.io.resources(1).clockEnable
    val cpuDrained = fabric.io.idle && links.map(_.fabricTransportEmpty).reduce(_ && _) &&
        cpuSpinorEmpty && vpuSpinorEmpty && time.sourceIdle
    val vpuDrained = cpuSpinorEmpty && vpuSpinorEmpty && (vectorAdmissionClosed || cpuIsStopped)
    // Drain approval is a lease. Only the managed-domain ACK returning low
    // releases it; unrelated activity in another running domain cannot fake wake progress.
    val cpuApproved = withClockAndReset(systemClock, systemRelease.resetOut) {
        val approved = RegInit(false.B)
        when(!cpuAck) { approved := false.B }
        when(cmu.io.resources(1).quiesce && cpuAck && cpuDrained) { approved := true.B }
        approved
    }
    val vpuApproved = withClockAndReset(systemClock, systemRelease.resetOut) {
        val approved = RegInit(false.B)
        when(!vpuAck) { approved := false.B }
        when(cmu.io.resources(2).quiesce && vpuAck && vpuDrained) { approved := true.B }
        approved
    }
    cmu.io.resources(1).ack := cpuApproved; cmu.io.resources(2).ack := vpuApproved
    io.cpuStopAck := cpuApproved; io.vpuStopAck := vpuApproved
}

/** Physical clock backend. GSIM uses the explicit-clock system above and drives
  * managed edges according to the CMU outputs; no fabric clk&enable gate exists.
  */
class I1SpinorManagedFpga(p: FiveStageConfig, systemHz: Int = 300000000,
    cpuHz: Long = 300000000L, vpuHz: Long = 300000000L) extends RawModule {
    val rawCpuClock = IO(Input(Clock())); val rawVpuClock = IO(Input(Clock()))
    val systemClock = IO(Input(Clock())); val commonColdReset = IO(Input(AsyncReset()))
    val unit = Module(new I1SpinorManagedSystem(p, systemHz, cpuHz, vpuHz))
    val io = IO(chiselTypeOf(unit.io)); io <> unit.io
    val cpuGate = Module(new ManagedClockBuffer(independentControlClock = true))
    val vpuGate = Module(new ManagedClockBuffer(independentControlClock = true))
    for ((gate, raw, enable) <- Seq((cpuGate, rawCpuClock, unit.io.cpuClockEnable),
        (vpuGate, rawVpuClock, unit.io.vpuClockEnable))) {
        gate.rawClock := raw; gate.controlClock.get := systemClock
        gate.commonReset := commonColdReset; gate.enable := enable
    }
    unit.cpuClock := cpuGate.managedClock; unit.vpuClock := vpuGate.managedClock
    unit.systemClock := systemClock; unit.commonColdReset := commonColdReset
}
