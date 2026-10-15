package ooo
import soc.core.ooo._

object ProofControlContractMain extends App {
    val p = ThreeProofRowNativeProfile.config.coreParams
    ProofControlContract.requireSupported(p)
    var rejected = 0
    def reject(candidate: => OooParams): Unit = {
        var caught = false
        try { ProofControlContract.requireSupported(candidate) }
        catch { case e: IllegalArgumentException =>
            require(e.getMessage.contains("proof control requires fast head trap and system recovery"),
                "a different upstream constraint failed before the explicit C1 contract: " + e.getMessage)
            caught = true
        }
        require(caught); rejected += 1
    }
    reject(p.copy(fastHeadTrapRecovery = false))
    reject(p.copy(fastHeadSystemRecovery = false, shareProtectedHeadPayload = false))
    require(p.residentMemoryPayloadReuse && !p.fastBufferedStoreRetire)
    println(s"PASS_C1_CONTRACT core=178 profile=95 fastHeadNegatives=$rejected inheritedFastStoreExclusion=true")
}
