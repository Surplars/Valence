package soc.ip.dma

import chisel3.util.isPow2

/** Independent, bounded packet-storage and memory-transaction capacities.
  * A legal elaboration is not evidence of line rate, timing closure, or a
  * software endpoint supporting every maximum-frame/window combination.
  */
case class NetworkDmaConfig(
    maxFrameBytes: Int = 2048,
    macRxSlots: Int = 4,
    postedRxSlots: Int = 4,
    memoryCredits: Int = 4,
    postedTxSlots: Int = 0
) {
    require(maxFrameBytes >= 64 && maxFrameBytes <= 16384 && isPow2(maxFrameBytes))
    require(macRxSlots >= 1 && macRxSlots <= 16 && isPow2(macRxSlots))
    require(postedRxSlots >= 1 && postedRxSlots <= 16 && isPow2(postedRxSlots))
    require(postedTxSlots == 0 || (postedTxSlots >= 1 && postedTxSlots <= 16 && isPow2(postedTxSlots)))
    require(memoryCredits >= 1 && memoryCredits <= 16 && isPow2(memoryCredits))
}

object NetworkDmaConfig {
    /** Keyed options coexist with the exporter's established positional ABI. */
    def parseArgs(args: Array[String]): (Array[String], NetworkDmaConfig) = {
        val keys = Set("network-frame-bytes", "network-mac-slots", "network-rx-slots", "network-memory-credits", "network-tx-slots")
        val options = args.filter(_.startsWith("--network-"))
        val pairs = options.map { option =>
            val parts = option.drop(2).split("=", -1)
            require(parts.length == 2 && keys.contains(parts(0)), s"unknown network option: $option")
            parts(0) -> parts(1).toInt
        }
        require(pairs.map(_._1).distinct.length == pairs.length, "duplicate network option")
        val values = pairs.toMap
        val config = NetworkDmaConfig(
            maxFrameBytes = values.getOrElse("network-frame-bytes", 2048),
            macRxSlots = values.getOrElse("network-mac-slots", 4),
            postedRxSlots = values.getOrElse("network-rx-slots", 4),
            memoryCredits = values.getOrElse("network-memory-credits", 4),
            postedTxSlots = values.getOrElse("network-tx-slots", 0))
        (args.filterNot(_.startsWith("--network-")), config)
    }

    val Default: NetworkDmaConfig = NetworkDmaConfig()
    // Serialized-capacity witness; reset still selects the legacy V1 software ABI.
    val Serialized: NetworkDmaConfig = NetworkDmaConfig(macRxSlots = 1, postedRxSlots = 1, memoryCredits = 1)
}
