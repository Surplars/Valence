package ip

import _root_.circt.stage.ChiselStage
import soc.ip.interrupt._

/** Scalar production APLIC ports, including the largest source vector. */
object AplicBoundaryGsimMain extends App {
    require(args.length == 4)
    ChiselStage.emitCHIRRTLFile(
        new Aplic(AplicParams(sources = args(1).toInt, identities = 2047,
            base = BigInt(args(2), 16), msiBase = BigInt(args(3), 16))),
        Array("--target-dir", args.head))
}
