package spinor_integration

import chisel3._
import chisel3.reflect.DataMirror
import _root_.circt.stage.ChiselStage
import soc.core.inorder.FiveStageConfig
import soc.integration.spinor.I1SpinorManagedSystem
import soc.ip.clock.{ContinuousClockBuffer, ManagedClockBuffer}

/** Registered port context for module OOC measurement, matching the earlier
  * CPU timing fixture. These registers are excluded from DUT resource counts.
  * No architectural stage or AXI protocol adapter is added to the system.
  * A real board must supply its own AXI/IO timing and complete clock/reset signoff.
  */
class I1System300Context(p: FiveStageConfig) extends RawModule {
    val rawCpuClock = IO(Input(Clock())); val rawVpuClock = IO(Input(Clock()))
    val systemClock = IO(Input(Clock())); val commonColdReset = IO(Input(AsyncReset()))
    val unit = Module(new I1SpinorManagedSystem(p))
    val alwaysOnBuffer = Module(new ContinuousClockBuffer)
    alwaysOnBuffer.rawClock := systemClock
    val cpuGate = Module(new ManagedClockBuffer(independentControlClock = true))
    val vpuGate = Module(new ManagedClockBuffer(independentControlClock = true))
    for ((gate, raw, enable) <- Seq((cpuGate, rawCpuClock, unit.io.cpuClockEnable),
        (vpuGate, rawVpuClock, unit.io.vpuClockEnable))) {
        gate.rawClock := raw; gate.controlClock.get := alwaysOnBuffer.runningClock
        gate.commonReset := commonColdReset; gate.enable := enable
    }
    unit.cpuClock := cpuGate.managedClock; unit.vpuClock := vpuGate.managedClock
    unit.systemClock := alwaysOnBuffer.runningClock; unit.commonColdReset := commonColdReset
    val io = IO(chiselTypeOf(unit.io))
    def capture(internal: Data, external: Data, localClock: Clock): Unit = (internal, external) match {
        case (a: Record, b: Record) =>
            a.elements.foreach { case (name, value) => capture(value, b.elements(name), localClock) }
        case (a: Vec[_], b: Vec[_]) =>
            a.getElements.zip(b.getElements).foreach { case (x, y) => capture(x, y, localClock) }
        case (a, b) => withClock(localClock) {
            DataMirror.directionOf(a) match {
                case ActualDirection.Input => a := RegNext(b)
                case ActualDirection.Output => b := RegNext(a)
                case direction => throw new IllegalArgumentException(s"unsupported timing port direction $direction")
            }
        }
    }
    unit.io.elements.foreach { case (name, port) =>
        val cpuObservation = name == "retire" || name == "protocolError"
        capture(port, io.elements(name), if (cpuObservation) cpuGate.managedClock else alwaysOnBuffer.runningClock)
    }
}
object I1HypervisorRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(new I1System300Context(I1HypervisorProfile.core),
        Array("--target-dir", args.head), Array("--split-verilog", "--lower-memories",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays"))
}
