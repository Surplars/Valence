package platform

import _root_.circt.stage.ChiselStage
import soc.ip.clock._
import soc.platform._

/** Elaboration only. Empty point tables intentionally authorize no rate. */
object CommonDynamicClockPlumbingMain extends App {
    require(args.length == 1)
    val p = CommonCpuProfile.I1Boot50
    ChiselStage.emitSystemVerilogFile(new ManagedPeripheralBank(p.cmu, p.cpuHz, p.uartHz,
        p.uartBaud, hardwareClocks = false, sourceClockHz = p.fabricHz,
        networkDmaConfig = p.fpga.network, triSpeedEthernet = true, triSpeedTxFrameSlots = 2,
        runtimeAdmission = true, runtimeControlPark = true, runtimeFixedMac = true,
        rateDomains = Some(Seq(ClockRateParams(maximumHz = 300000000L),
            ClockRateParams(maximumHz = 250000000L))), runtimeRateControl = true), Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}

/** Actual platform composition, no synthetic rate permission and no MMCM model. */
object CommonDynamicPlatformMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new CommonMachinePlatform(CommonCpuProfile.I1Boot50Dynamic,
        hardwareClocks = false, independentDdrClock = true, independentTimebaseClock = true,
        independentDebugClock = true, runtimeDebugAdmission = true, runtimeNetworkAdmission = true,
        runtimeFixedQualification = true, runtimeControlQualification = true, runtimeFixedMac = true,
        runtimeRateControl = true, externalIrqsAbsent = true), Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
