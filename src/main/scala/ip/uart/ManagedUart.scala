package soc.ip.uart

import chisel3._
import chisel3.util._
import soc.ip.bus._
import soc.ip.clock._

/** Actual retention UART endpoint: source MMIO wake proxy + one-credit CDC,
  * full UART drain, raw-clock ingress retention and physical gate. UART RX is
  * delayed 64+ raw cycles so the FIRST character can arrive after wake opens.
  * hardwareClocks=false is a single-clock functional export only, never a
  * replacement gate or independent-clock/physical timing qualification.
  */
class ManagedUart(cpuHz: Int = 100000000, rawHz: Int = 50000000, aonHz: Int = 50000000,
    baud: Int = 460800, hardwareClocks: Boolean = true) extends RawModule {
    val sourceClock = IO(Input(Clock()))
    val rawClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val registers = IO(Flipped(new RegisterPort))
    val control = IO(Flipped(new ClockResourceControl))
    val rx = IO(Input(Bool()))
    val tx = IO(Output(Bool()))
    val irq = IO(Output(Bool()))
    val managedClock = IO(Output(Clock()))
    val localIdle = IO(Output(Bool()))
    val cpuRelease = Module(new CdcResetRelease)
    cpuRelease.clockIn := sourceClock
    cpuRelease.asyncReset := commonReset
    val gatedClock = if (hardwareClocks) {
        val gate = Module(new ManagedClockBuffer)
        gate.rawClock := rawClock
        gate.commonReset := commonReset
        gate.enable := control.clockEnable
        gate.managedClock
    } else rawClock
    managedClock := gatedClock
    val bridge = Module(new RegisterClockDomainBridge)
    bridge.sourceClock := sourceClock
    bridge.destinationClock := gatedClock
    bridge.commonReset := commonReset
    val proxy = withClockAndReset(sourceClock, cpuRelease.resetOut) { Module(new ClockRegisterAdmission) }
    proxy.io.upstream <> registers
    proxy.io.downstream <> bridge.source
    proxy.io.quiesce := ManagedPeripheralSupport.level(control.quiesce, sourceClock, cpuRelease.resetOut)
    proxy.io.isolate := ManagedPeripheralSupport.level(control.isolate, sourceClock, cpuRelease.resetOut)
    proxy.io.downstreamIdle := bridge.sourceIdle
    val ingress = Module(new PeripheralWakeDelay(1, ManagedPeripheralSupport.wakeDelay(rawHz, cpuHz, aonHz), 1))
    ingress.rawClock := rawClock
    ingress.commonReset := commonReset
    // Synchronize the asynchronous pad BEFORE the always-on delay line.
    val rawRelease = Module(new CdcResetRelease)
    rawRelease.clockIn := rawClock
    rawRelease.asyncReset := commonReset
    val sampledRx = withClockAndReset(rawClock, rawRelease.resetOut) {
        val meta = RegNext(rx, true.B)
        val synced = RegNext(meta, true.B)
        addAttribute(meta, "ASYNC_REG = \"TRUE\"")
        addAttribute(synced, "ASYNC_REG = \"TRUE\"")
        synced
    }
    ingress.payload := sampledRx.asUInt
    ingress.active := !sampledRx
    ingress.quiesce := control.quiesce
    ingress.isolate := control.isolate
    val receiverWake = ManagedPeripheralSupport.level(ingress.wake, sourceClock, cpuRelease.resetOut)
    control.wake := withClockAndReset(sourceClock, cpuRelease.resetOut) {
        RegNext(proxy.io.wake || receiverWake, false.B)
    }
    val uart = withClockAndReset(gatedClock, bridge.destinationReset) {
        Module(new UartConsole(clockHz = rawHz, fastDivisorOne = true, referenceClockHz = baud * 16))
    }
    uart.io.mmio <> bridge.destination
    uart.io.rx := ingress.delayed.asBool
    // UART may stop only at idle-high TX; retained break blocks the drain.
    tx := uart.io.tx
    val cpuDrained = withClockAndReset(sourceClock, cpuRelease.resetOut) { RegNext(proxy.io.drained, false.B) }
    val sourceDrained = ManagedPeripheralSupport.level(cpuDrained, gatedClock, bridge.destinationReset)
    localIdle := uart.io.idle && bridge.destinationIdle && sourceDrained && ingress.empty
    val agent = Module(new PeripheralQuiesceAck)
    agent.domainClock := gatedClock
    agent.commonReset := commonReset
    agent.quiesce := control.quiesce
    agent.idle := localIdle
    control.ack := agent.ack
    val irqLevel = withClockAndReset(gatedClock, bridge.destinationReset) { RegNext(uart.io.irq, false.B) }
    irq := ManagedPeripheralSupport.level(irqLevel, sourceClock, cpuRelease.resetOut)
}
