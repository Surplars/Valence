package ip

import _root_.circt.stage.ChiselStage
import soc.ip.ethernet._

/** Standalone boundaries retain test-facing ports that a production hierarchy
  * can legally prune. Exporting does not run independent-clock or pad tests.
  */
object TriSpeedNativeRtlMain extends App {
    private val options = Array("--split-verilog", "-disable-all-randomization", "-strip-debug-info")
    ChiselStage.emitSystemVerilogFile(new TriSpeedRgmiiTx,
        Array("--target-dir", args.head + "/tx"), options)
    ChiselStage.emitSystemVerilogFile(new EthernetPhysicalIngress(64),
        Array("--target-dir", args.head + "/ingress"), options)
    ChiselStage.emitSystemVerilogFile(new EthernetRxClockWatchdog,
        Array("--target-dir", args.head + "/watchdog"), options)
}
