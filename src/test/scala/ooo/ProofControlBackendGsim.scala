package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}

object ProofControlBackendMain extends App {
    require(args.length == 2 && Set("baseline", "shadow").contains(args(1)))
    val out = Paths.get(args(0)); require(!Files.exists(out), "fresh output required")
    var actual: Option[soc.core.ooo.OooParams] = None
    ChiselStage.emitCHIRRTLFile({
        val dut = new ReadyStoreQuery77BackendGsim(true, proofRows = 3,
            preselectRedirectTokenMatches = true, shadowEarlyProofBind = args(1) == "shadow",
            proofControlInputs = true)
        actual = Some(dut.backend.p)
        require(dut.backend.p == ThreeProofRowNativeProfile.config.coreParams)
        dut
    }, Array("--target-dir", out.toString))
    Files.writeString(out.resolve("actual-core.json"), PostedBoardConfiguration.json(actual.get) + "\n")
}
