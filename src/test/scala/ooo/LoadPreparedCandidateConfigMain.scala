package ooo
object LoadPreparedCandidateConfigMain extends App {
    val p = FlushLoadPublishConfig.params(true)
    require(p.pendingVirtualStoreProof && !p.memoryProofFrontier && p.registeredLoadResultReady && p.localTaggedResponseReady)
    var rejected = false
    try { p.copy(memoryProofFrontier = true) }
    catch { case e: IllegalArgumentException =>
        require(e.getMessage.contains("pending virtual-store proofs support only"))
        rejected = true
        println("CANDIDATE_CONFIG_REJECT_REACHED pending_frontier_conflict: " + e.getMessage)
    }
    require(rejected, "pending proof/frontier conflict escaped original OooParams contract")
    val generic = soc.core.ooo.OooParams()
    require(!(generic.pendingVirtualStoreProof && generic.registeredLoadResultReady && generic.localTaggedResponseReady))
    println("LOAD_PREPARED_CANDIDATE_CONFIG_PASS no_profile_field_changes")
}
