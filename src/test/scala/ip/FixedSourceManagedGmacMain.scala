package ip

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.ip.ethernet._

/** Fixture-only shorter policy waits. Divider and all other timeout frequencies
  * use the actual continuous 125 MHz source; fabric frequency never enters MAC.
  */
class FixedSourceTestMac extends TriSpeedManagedGmac(cpuHz = 125000000, hardwareClocks = false,
    txFrameSlots = 2, runtimeAdmission = true, runtimeControlPark = true, exportContinuousClock = true) {
    override protected def buildPhyManager(): Rtl8211fPhyManager =
        new Rtl8211fPhyManager(125000000, startupCycles = 256, pollCycles = 512, runtimePark = true)
}
class FixedSourceTestGmac(heldResponseStorage: Boolean = false) extends FixedSourceManagedGmac(
    hardwareClocks = false, heldResponseStorage = heldResponseStorage) {
    override protected def buildMac(): TriSpeedManagedGmac = new FixedSourceTestMac
}
object FixedSourceManagedGmacMain extends App {
    require(args.length == 2, "usage: FixedSourceManagedGmacMain <rtl-dir> test|production|balanced|boundary|test-held|production-held|balanced-held|boundary-held")
    ChiselStage.emitSystemVerilogFile(args(1) match {
        case "test" => new FixedSourceTestGmac
        case "production" => new FixedSourceManagedGmac
        case "balanced" => new FixedSourceManagedGmac(balancedRawClock = true)
        case "boundary" => new FixedMacBoundary
        case "test-held" => new FixedSourceTestGmac(heldResponseStorage = true)
        case "production-held" => new FixedSourceManagedGmac(heldResponseStorage = true)
        case "balanced-held" => new FixedSourceManagedGmac(balancedRawClock = true, heldResponseStorage = true)
        case "boundary-held" => new FixedMacBoundary(heldResponseStorage = true)
        case _ => throw new IllegalArgumentException("unknown fixed MAC emission mode")
    }, Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization", "--preserve-values=named",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays", "--default-layer-specialization=enable"))
}
