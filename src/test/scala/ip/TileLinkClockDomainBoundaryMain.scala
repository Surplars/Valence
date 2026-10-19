package ip

import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.TLParams
import soc.ip.tilelink.TileLinkClockDomainBoundary

/** Explicit two-clock component profile; not a CPU/board boot or timing claim. */
object TileLinkClockDomainBoundaryMain extends App {
    require(args.length == 1 || args.length == 2,
        "usage: TileLinkClockDomainBoundaryMain <fresh-output-directory> [baseline|held]")
    val storage = args.lift(1).getOrElse("baseline")
    require(Set("baseline", "held").contains(storage), "storage must be baseline or held")
    val held = storage == "held"
    ChiselStage.emitSystemVerilogFile(new TileLinkClockDomainBoundary(
        TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 1),
        depth = if (held) 16 else 4, heldResponseStorage = held),
        Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
