package ip

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.bus._
import soc.ip.clock._
import soc.bus.tilelink._
import soc.core.ooo.{CoreRegisterRouter, DataPort, ParallelRegisterRouter}

object CmuTestConfig {
    val params = CmuParams(50000000, Seq(ClockResource("AON", 50000000),
        ClockResource("CPU", 100000000), ClockResource("PERIPH", 50000000, canGate = true),
        ClockResource("NET", 125000000, canGate = true), ClockResource("ABSENT", 0, present = false)),
        timeoutCycles = 32)
}

class CmuTestSignals extends Bundle {
    val ack = Input(UInt(5.W))
    val wake = Input(UInt(5.W))
    val enabled = Output(UInt(5.W))
    val quiesce = Output(UInt(5.W))
    val isolate = Output(UInt(5.W))
    val admission = Output(UInt(5.W))
    val irq = Output(Bool())
    def connect(resources: Vec[ClockResourceControl], interrupt: Bool): Unit = {
        for (n <- 0 until 5) { resources(n).ack := ack(n); resources(n).wake := wake(n) }
        enabled := VecInit(resources.map(_.clockEnable)).asUInt
        quiesce := VecInit(resources.map(_.quiesce)).asUInt
        isolate := VecInit(resources.map(_.isolate)).asUInt
        admission := VecInit(resources.map(_.allowAdmission)).asUInt
        irq := interrupt
    }
}

class ClockManagementGsim extends Module {
    val io = IO(new Bundle { val control = Flipped(new RegisterPort); val signals = new CmuTestSignals })
    val cmu = Module(new ClockManagementUnit(CmuTestConfig.params))
    cmu.io.registers <> io.control
    io.signals.connect(cmu.io.resources, cmu.io.irq)
}

class ClockManagementTlGsim extends Module {
    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4)))
        val signals = new CmuTestSignals
    })
    val cmu = Module(new TileLinkClockManagement(CmuTestConfig.params))
    cmu.io.tl <> io.tl
    io.signals.connect(cmu.io.resources, cmu.io.irq)
}

/** Both real CPU MMIO router variants, no CPU execution or memory model. */
class ClockManagementRouterGsim(parallel: Boolean) extends Module {
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val memory = new DataPort
        val signals = new CmuTestSignals
    })
    val cmu = Module(new ClockManagementUnit(CmuTestConfig.params))
    if (parallel) {
        val router = Module(new ParallelRegisterRouter(Seq((BigInt("10080000", 16), BigInt(4096))),
            bypassMemoryShift = true))
        router.io.upstream <> io.upstream
        io.memory <> router.io.memory
        cmu.io.registers <> router.io.registers(0)
    } else {
        val router = Module(new CoreRegisterRouter(BigInt("10080000", 16), 4096))
        router.io.upstream <> io.upstream
        io.memory <> router.io.memory
        cmu.io.registers <> router.io.registers
    }
    io.signals.connect(cmu.io.resources, cmu.io.irq)
}

/** Gate and handshake CDC only: no CSR, CPU, memory, MAC or PHY. */
class ManagedClockCdcTop extends RawModule {
    val alwaysOnClock = IO(Input(Clock()))
    val rawClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val stop = IO(Input(Bool()))
    val wake = IO(Input(Bool()))
    val idle = IO(Input(Bool()))
    val clearFault = IO(Input(Bool()))
    val managedClock = IO(Output(Clock()))
    val enabled = IO(Output(Bool()))
    val quiesce = IO(Output(Bool()))
    val isolate = IO(Output(Bool()))
    val admission = IO(Output(Bool()))
    val stopped = IO(Output(Bool()))
    val fault = IO(Output(Bool()))
    val domainAck = IO(Output(Bool()))
    val release = Module(new CdcResetRelease)
    release.clockIn := alwaysOnClock
    release.asyncReset := commonReset
    val policy = withClockAndReset(alwaysOnClock, release.resetOut) {
        Module(new PeripheralClockControl(32, 3))
    }
    policy.io.stopRequest := stop
    policy.io.wake := wake
    policy.io.clearFault := clearFault
    val gate = Module(new ManagedClockBuffer)
    gate.rawClock := rawClock
    gate.commonReset := commonReset
    gate.enable := policy.io.clockEnable
    managedClock := gate.managedClock
    val agent = Module(new PeripheralQuiesceAck)
    agent.domainClock := gate.managedClock
    agent.commonReset := commonReset
    agent.quiesce := policy.io.quiesce
    agent.idle := idle
    policy.io.domainAck := agent.ack
    domainAck := agent.ack
    enabled := policy.io.clockEnable
    quiesce := policy.io.quiesce
    isolate := policy.io.isolate
    admission := policy.io.allowAdmission
    stopped := policy.io.stopped
    fault := policy.io.fault
}

object ClockManagementGsimMain extends App {
    val top = args(1) match {
        case "register" => () => new ClockManagementGsim
        case "tl" => () => new ClockManagementTlGsim
        case "serial" => () => new ClockManagementRouterGsim(false)
        case "parallel" => () => new ClockManagementRouterGsim(true)
    }
    ChiselStage.emitCHIRRTLFile(top(), Array("--target-dir", args.head))
}
object ClockManagementRtlMain extends App {
    val options = Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization")
    ChiselStage.emitSystemVerilogFile(new FpgaClockResources(CmuTestConfig.params),
        Array("--target-dir", args.head + "/bank"), options)
    ChiselStage.emitSystemVerilogFile(new ManagedClockCdcTop,
        Array("--target-dir", args.head + "/cdc"), options)
}
