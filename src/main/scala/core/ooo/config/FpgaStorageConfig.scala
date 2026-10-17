package soc.core.ooo

/** Explicit storage topology choices; neither changes width, capacity or latency. */
case class FpgaStorageConfig(bankedRobPayload: Boolean = false, sharedStoreOperandReads: Boolean = false,
    lvtPhysicalRegisterFile: Boolean = false, bankedIssuePayload: Boolean = false, bankedFetchHints: Boolean = false,
    shareProtectedHeadPayload: Boolean = false, reconstructIssueTokenIndex: Boolean = false,
    sharedMemoryAddressState: Boolean = false) {
    def configure(p: OooParams): OooParams = p.copy(
        bankedRobPayload = bankedRobPayload, sharedStoreOperandReads = sharedStoreOperandReads,
        lvtPhysicalRegisterFile = lvtPhysicalRegisterFile,
        bankedIssuePayload = bankedIssuePayload, bankedFetchHints = bankedFetchHints,
        shareProtectedHeadPayload = shareProtectedHeadPayload, reconstructIssueTokenIndex = reconstructIssueTokenIndex,
        sharedMemoryAddressState = sharedMemoryAddressState)
    def enabled: Boolean = bankedRobPayload || sharedStoreOperandReads || lvtPhysicalRegisterFile ||
        bankedIssuePayload || bankedFetchHints || shareProtectedHeadPayload || reconstructIssueTokenIndex ||
        sharedMemoryAddressState
}

object FpgaStorageConfig {
    val Registers = FpgaStorageConfig()
    val BankedShared = FpgaStorageConfig(bankedRobPayload = true, sharedStoreOperandReads = true)
    def parseArgs(args: Array[String]): (Array[String], FpgaStorageConfig) = {
        val keys = Set("--banked-rob", "--shared-store-reads", "--lvt-prf", "--banked-issue-payload", "--banked-fetch-hints", "--share-protected-head-payload", "--reconstruct-issue-token-index", "--shared-memory-address-state")
        keys.foreach(key => require(args.count(_ == key) <= 1, s"duplicate FPGA storage flag: $key"))
        require(!args.exists(_.startsWith("--reconstruct-issue-token-index=")),
            "--reconstruct-issue-token-index does not accept a value")
        require(!args.exists(_.startsWith("--shared-memory-address-state=")),
            "--shared-memory-address-state does not accept a value")
        (args.filterNot(keys.contains), FpgaStorageConfig(
            bankedRobPayload = args.contains("--banked-rob"),
            sharedStoreOperandReads = args.contains("--shared-store-reads"),
            lvtPhysicalRegisterFile = args.contains("--lvt-prf"),
            bankedIssuePayload = args.contains("--banked-issue-payload"),
            bankedFetchHints = args.contains("--banked-fetch-hints"),
            shareProtectedHeadPayload = args.contains("--share-protected-head-payload"),
            reconstructIssueTokenIndex = args.contains("--reconstruct-issue-token-index"),
            sharedMemoryAddressState = args.contains("--shared-memory-address-state")))
    }
}
