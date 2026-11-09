package spinor_cmu_test

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.bus._
import soc.ip.clock._
import soc.bus.tilelink._

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

object I1CmuMain extends App {
    ChiselStage.emitCHIRRTLFile(new ClockManagementGsim, Array("--target-dir", args.head))
}
