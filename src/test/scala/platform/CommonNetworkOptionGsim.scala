package platform

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.ip.bus.RegisterPort
import soc.ip.clock.ManagedPeripheralBank
import soc.platform.{CommonCpuProfile, CommonPeripheralConfig, CommonSocConfig}

/** Two static network-absent compositions, with the same production Fabric.
  * No CPU, PHY, runtime clock transition or board behavior is claimed.
  */
object CommonNetworkOptionGsimMain extends App {
    require(args.length == 2 && Set("on", "off").contains(args(1)),
        "fresh output directory and on|off remaining-producers selection required")
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    val producers = args(1) == "on"
    ChiselStage.emitCHIRRTLFile(new CommonMachineFabricFlatGsim(runtime = false,
        jtagDownload = producers, memoryCopyDma = producers, network = false),
        Array("--target-dir", args(0)))
}

/** Actual managed UART/CMU with network absent. Clocks are intentionally aliased
  * for bounded functional checks, not CDC or physical gating qualification.
  * Retain the real asynchronous reset in emitted FIR; no implicit text rewrite.
  */
class CommonManagedNetworkOffGsim extends Module {
    val io = IO(new Bundle {
        val cmu = Flipped(new RegisterPort)
        val uart = Flipped(new RegisterPort)
        val uartRx = Input(Bool())
        val uartTx = Output(Bool())
        val uartIrq = Output(Bool())
        val cmuIrq = Output(Bool())
        val enabled = Output(UInt(7.W))
        val quiesce = Output(UInt(7.W))
        val isolate = Output(UInt(7.W))
    })
    val config = CommonSocConfig(CommonCpuProfile.A1,
        peripherals = CommonPeripheralConfig(network = false))
    val bank = Module(new ManagedPeripheralBank(config.cmu, hardwareClocks = false, networkEnabled = false))
    bank.sourceClock := clock
    bank.alwaysOnClock := clock
    bank.rawUartClock := clock
    bank.commonReset := reset.asBool.asAsyncReset
    bank.cmuRegisters <> io.cmu
    bank.uartRegisters <> io.uart
    bank.uartRx := io.uartRx
    io.uartTx := bank.uartTx
    io.uartIrq := bank.uartIrq
    io.cmuIrq := bank.cmuIrq
    io.enabled := bank.enabled
    io.quiesce := bank.quiesce
    io.isolate := bank.isolate
}

object CommonManagedNetworkOffGsimMain extends App {
    require(args.length == 1, "fresh output directory required")
    require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    ChiselStage.emitCHIRRTLFile(new CommonManagedNetworkOffGsim, Array("--target-dir", args(0)))
}
