package ooo
import java.nio.file.{Files, Paths}
import java.security.MessageDigest
import soc.core.ooo._
/** Explicit field bridge from the immutable published default52 product. */
private[ooo] object RetirementIntentCpuProfile {
    val flag = "--retirement-intent"
    val root = Iterator.iterate(Paths.get("").toAbsolutePath)(_.getParent)
        .takeWhile(_ != null).find(p => Files.isRegularFile(p.resolve("build.mill"))).get
    private def sha(bytes: Array[Byte]): String = MessageDigest.getInstance("SHA-256").digest(bytes)
        .map(b => f"${b & 0xff}%02x").mkString
    private val baseFile = root.resolve("fpga/next/timing-batch-owner-row-profile.json")
    require(sha(Files.readAllBytes(baseFile)) == "32063adb7dd598ea5fcd014eee71c02d599139a59bf69287598f780a35d6d923")
    private val list = "(?s)\"native_options\"\\s*:\\s*\\[(.*?)\\]".r
        .findFirstMatchIn(Files.readString(baseFile)).get.group(1)
    val defaultOptions: Seq[String] = "\"([^\"]*)\"".r.findAllMatchIn(list).map(_.group(1)).toSeq
    val candidateOptions: Seq[String] = defaultOptions :+ flag
    require(defaultOptions.size == 52 && defaultOptions.distinct.size == 52)
    FpgaNextProfileOptions.validate(candidateOptions)
    val off = FpgaNextConfig.fromOptions(defaultOptions.toSet, defaultSelected = false)
    val on = FpgaNextConfig.fromOptions(candidateOptions.toSet, defaultSelected = false)
    private val snapshot = root.resolve("fpga/next/timing-batch-head-drain-default52.json")
    require(sha(Files.readAllBytes(snapshot)) == "87edfc04e59fce76873b83c236d694bc10a503497ba0a9e06534cf91327b9622")
    private val frozen = Files.readString(snapshot).trim
    private def strip(p: Product): Map[String, Any] = {
        val values = p.productElementNames.zip(p.productIterator).toMap
        require(values.get("retirementIntent").contains(false), "only the named false addition may be projected")
        values - "retirementIntent"
    }
    private val bridged = PostedBoardConfiguration.document(off) ++ Map(
        "profile" -> strip(off), "core" -> strip(off.coreParams))
    require(PostedBoardConfiguration.json(bridged) == frozen, "complete immutable default52 product differs")
    require(on.copy(retirementIntent = false) == off && on.coreParams.copy(retirementIntent = false) == off.coreParams)
    def requireExact(c: FpgaNextConfig): Unit = {
        HeadDrainActualAudit.requireShape(c)
        require(c == (if (c.retirementIntent) on else off))
        require(!c.predecodedHeadDrain && !c.coreParams.predecodedHeadDrain && !c.futureHomeWayReservation &&
            !c.storePrefetchLruVictim && !c.cache.futureHomeWayReservation && !c.cache.storePrefetchLruVictim &&
            !c.eagerFetchPrefixSelect, "only retirement intent may be enabled over default52")
        require(c.coreParams.robEntries == 16 && c.coreParams.physicalRegs == 48 && c.coreParams.tagBits == 64)
    }
}
