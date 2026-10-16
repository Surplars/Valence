package ooo
import _root_.circt.stage.ChiselStage
import java.nio.file.{Files,Paths}
object PoolCurrentBackendMain extends App {
    require(args.length == 2 && Set("baseline", "pool").contains(args(1)))
    val out = Paths.get(args(0)); require(!Files.exists(out))
    ChiselStage.emitCHIRRTLFile({
        val dut = new ReadyStoreQuery77BackendGsim(true, proofRows = 3,
            preselectRedirectTokenMatches = false, proofControlInputs = true,
            factorPreparedStorePool = args(1) == "pool")
        require(dut.backend.p == ThreeProofRowNativeProfile.config.coreParams)
        require(!dut.backend.preselectRedirectTokenMatches && !dut.backend.proofBankOwnerCleanup &&
            !dut.backend.proofBankQuiesceIntent && !dut.backend.shadowEarlyProofBind)
        require(dut.backend.factorPreparedStorePool == (args(1) == "pool"))
        require(dut.backend.p.residentMemoryPayloadReuse && dut.backend.p.preparedStoreLookahead &&
            !dut.backend.p.postedPreparationPriority)
        dut
    }, Array("--target-dir", out.toString))
    Files.writeString(out.resolve("actual-core.json"),
        PostedBoardConfiguration.json(ThreeProofRowNativeProfile.config.coreParams) + "\n")
    Files.writeString(out.resolve("actual-pool.json"),ujson.Obj("pool" -> (args(1) == "pool"),
        "c0" -> false, "c1" -> false,"nativeTopQualified" -> false).render(2) + "\n")
}
