package ooo

import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Reads the selected production packet constructor; adds no hardware. */
object EagerPrefixActualAudit {
    def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
        val core = platform.core.core.core
        val packet = core.fetchPacket.getOrElse(
            throw new IllegalArgumentException("actual registered fetch packet is absent"))
        require(core.p == expected.coreParams)
        require(packet.eagerPrefixSelect == core.p.eagerFetchPrefixSelect &&
            packet.eagerPrefixSelect == expected.eagerFetchPrefixSelect,
            "actual selected packet eager prefix flag differs")
        require(packet.alignedPermissionStage == core.p.alignedFetchPermissionStage)
        require(!packet.eagerPrefixSelect || packet.alignedPermissionStage)
        Map("schema" -> "actual-eager-prefix-v1",
            "eagerFetchPrefixSelect" -> core.p.eagerFetchPrefixSelect,
            "alignedPermissionStage" -> packet.alignedPermissionStage,
            "selectedPacketEagerPrefixSelect" -> packet.eagerPrefixSelect)
    }
    def write(actual: Map[String, Any], directory: String): Unit = {
        def json(value: Any): String = value match {
            case text: String => "\"" + text + "\""
            case value: Boolean => value.toString
            case _ => throw new IllegalArgumentException("unsupported eager prefix audit value")
        }
        val text = actual.toSeq.sortBy(_._1).map { case (key, value) => json(key) + ":" + json(value) }
            .mkString("{", ",", "}\n")
        Files.writeString(Paths.get(directory, "actual-eager-prefix.json"), text)
    }
}
