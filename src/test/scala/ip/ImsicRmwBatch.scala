package ip

import _root_.circt.stage.ChiselStage
import soc.ip.interrupt._

/** Four architectural files and two bitmap words exercise bank-local CSR RMW. */
object ImsicRmwBatchMain extends App {
    ChiselStage.emitSystemVerilogFile(
        new Imsic(ImsicParams(identities = 127, guestFiles = 2)),
        Array("--target-dir", args.head),
        firtoolOpts = Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}
