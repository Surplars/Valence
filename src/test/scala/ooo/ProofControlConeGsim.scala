package ooo
import chisel3._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Every production backend IO remains symbolic: no cache/posted/control tie-offs. */
class ProofControlConeGsim(enabled: Boolean) extends Module {
    val profile = ThreeProofRowNativeProfile.config
    val backend = Module(ReadyStoreQuery77BackendFactory.create(profile,
        preselectRedirectTokenMatches = true, shadowEarlyProofBind = enabled,
        proofBankQuiesceIntent = enabled, proofBankOwnerCleanup = enabled))
    val io = IO(chiselTypeOf(backend.io))
    io <> backend.io
    require(backend.p == profile.coreParams)
}
object ProofControlConeMain extends App {
    require(args.length == 2 && Set("baseline", "cleanup").contains(args(1)))
    ChiselStage.emitCHIRRTLFile(new ProofControlConeGsim(args(1) == "cleanup"),
        Array("--target-dir", args(0)))
}
