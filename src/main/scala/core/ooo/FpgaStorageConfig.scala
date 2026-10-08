package soc.core.ooo

/** Explicit storage topology choices; neither changes width, capacity or latency. */
case class FpgaStorageConfig(bankedRobPayload: Boolean = false, sharedStoreOperandReads: Boolean = false,
    lvtPhysicalRegisterFile: Boolean = false) {
    def configure(p: OooParams): OooParams = p.copy(
        bankedRobPayload = bankedRobPayload, sharedStoreOperandReads = sharedStoreOperandReads,
        lvtPhysicalRegisterFile = lvtPhysicalRegisterFile)
    def enabled: Boolean = bankedRobPayload || sharedStoreOperandReads || lvtPhysicalRegisterFile
}

object FpgaStorageConfig {
    val Registers = FpgaStorageConfig()
    val BankedShared = FpgaStorageConfig(bankedRobPayload = true, sharedStoreOperandReads = true)
    def parseArgs(args: Array[String]): (Array[String], FpgaStorageConfig) = {
        val keys = Set("--banked-rob", "--shared-store-reads", "--lvt-prf")
        keys.foreach(key => require(args.count(_ == key) <= 1, s"duplicate FPGA storage flag: $key"))
        (args.filterNot(keys.contains), FpgaStorageConfig(
            bankedRobPayload = args.contains("--banked-rob"),
            sharedStoreOperandReads = args.contains("--shared-store-reads"),
            lvtPhysicalRegisterFile = args.contains("--lvt-prf")))
    }
}
