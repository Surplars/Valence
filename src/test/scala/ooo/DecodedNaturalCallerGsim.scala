package ooo

import _root_.circt.stage.ChiselStage

class DecodedNaturalBufferedLoadProofGsim extends BufferedLoadProofGsim(
    sourceLocalCancellation = true, sharedPmpBounds = true, decodedPmp = true)
class DecodedNaturalWalkerGsim extends FixedPmpWalkerGsim(3, decodedPmp = true)
class DecodedNaturalCertifiedChainGsim extends CertifiedIngressChainGsim(true,
    Some("full-r1-m3-efficiency-refactor-2"))

object DecodedNaturalBufferedLoadProofGsimMain extends App {
    require(args.length == 1, "output-directory")
    ChiselStage.emitCHIRRTLFile(new DecodedNaturalBufferedLoadProofGsim, Array("--target-dir", args.head))
}
object DecodedNaturalWalkerGsimMain extends App {
    require(args.length == 1, "output-directory")
    ChiselStage.emitCHIRRTLFile(new DecodedNaturalWalkerGsim, Array("--target-dir", args.head))
}
object DecodedNaturalCertifiedChainGsimMain extends App {
    require(args.length == 1, "output-directory")
    ChiselStage.emitCHIRRTLFile(new DecodedNaturalCertifiedChainGsim, Array("--target-dir", args.head))
}
