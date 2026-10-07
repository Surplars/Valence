package ip

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.bus._
import soc.ip.clock._
import soc.ip.ethernet._
import soc.core.ooo.BoardSocConfig

object ManagedPeripheralTestConfig {
    val params = CmuParams(50000000,
        BoardSocConfig.clockResources(50000000, 100000000, 50000000, false, 250000000, true)
            .zipWithIndex.map { case (resource, n) => resource.copy(canGate = Set(3, 5, 6).contains(n)) },
        timeoutCycles = 4096)
}

/** Aliased single clock functional model of real UART/framing/adapter/control.
  * No physical gate and no independent-edge claim; exports actual hardware
  * separately. Program/CPU/memory/PHY execution is deliberately absent.
  */
class ManagedPeripheralGsim extends Module {
    val io = IO(new Bundle {
        val cmu = Flipped(new RegisterPort)
        val uart = Flipped(new RegisterPort)
        val gmac = Flipped(new RegisterPort)
        val streams = new ManagedGmacStreams
        val uartRx = Input(Bool())
        val uartTx = Output(Bool())
        val rxData = Input(UInt(8.W))
        val rxValid = Input(Bool())
        val rxError = Input(Bool())
        val txData = Output(UInt(8.W))
        val txEnable = Output(Bool())
        val txError = Output(Bool())
        val enabled = Output(UInt(7.W))
        val quiesce = Output(UInt(7.W))
        val isolate = Output(UInt(7.W))
        val irq = Output(UInt(3.W))
    })
    val bank = Module(new ManagedPeripheralBank(ManagedPeripheralTestConfig.params, hardwareClocks = false))
    bank.sourceClock := clock
    bank.alwaysOnClock := clock
    bank.rawUartClock := clock
    bank.rawTxClock := clock
    bank.rawRxClock := clock
    bank.commonReset := reset.asBool.asAsyncReset
    bank.cmuRegisters <> io.cmu
    bank.uartRegisters <> io.uart
    bank.gmacRegisters <> io.gmac
    bank.streams <> io.streams
    bank.uartRx := io.uartRx
    bank.gmiiRxData := io.rxData
    bank.gmiiRxValid := io.rxValid
    bank.gmiiRxError := io.rxError
    bank.linkUp := true.B
    bank.mdioIn := true.B
    io.uartTx := bank.uartTx
    io.txData := bank.gmiiTxData
    io.txEnable := bank.gmiiTxEnable
    io.txError := bank.gmiiTxError
    io.enabled := bank.enabled
    io.quiesce := bank.quiesce
    io.isolate := bank.isolate
    io.irq := Cat(bank.cmuIrq, bank.gmacIrq, bank.uartIrq)
}

object ManagedPeripheralsGsimMain extends App {
    // Pinned GSIM mis-emits duplicated derived async-reset aliases. Only this
    // ALL-CLOCK-ALIASED model samples reset at a step; production SV and the
    // independent-clock CDC xsim retain the real asynchronous reset behavior.
    val fir = ChiselStage.emitCHIRRTL(new ManagedPeripheralGsim)
    val sampled = fir.replace("AsyncReset", "UInt<1>").replace("asUInt<1>(", "asUInt(")
    val output = os.Path(args.head, os.pwd)
    os.makeDir.all(output)
    os.write(output / "ManagedPeripheralGsim.fir", sampled)
}
object ManagedPeripheralsRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(new ManagedPeripheralBank(
        ManagedPeripheralTestConfig.params.copy(timeoutCycles = 65536)),
        Array("--target-dir", args.head),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization"))
}
