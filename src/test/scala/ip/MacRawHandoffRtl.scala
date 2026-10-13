package ip

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.ip.ethernet._

/** Full production MAC exports for the bounded native handoff gate. */
object MacRawHandoffRtlMain extends App {
    val options = Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization")
    def generator: RawModule = if (args.lift(1).contains("baseline")) new MacRawHandoffBaseline(hardwareClocks = true, txFrameSlots = 2)
        else new TriSpeedManagedGmac(hardwareClocks = true, txFrameSlots = 2, rawClockHandoff = args.lift(1).contains("on"))
    ChiselStage.emitSystemVerilogFile(generator,
        Array("--target-dir", args.head), options)
}
