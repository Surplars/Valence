package ooo

import java.nio.file.{Files, Paths}

/** Constructor-only current-shape report for strict comparison to immutable A JSON. */
object YoungLoadSealProfileMain extends App {
    require(args.length == 2 && Set("off", "on").contains(args(1)), "fresh output directory and off/on required")
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh constructor output directory required")
    val c = NearTermAProfile.on.copy(postedYoungerLoadSealDeferral = args(1) == "on")
    require(!c.triSpeedRawClockHandoff)
    YoungLoadSealSourceBridge.requireCompatible(c)
    PostedBoardConfiguration.write(c, out.toString)
    YoungLoadSealSourceBridge.write(c, out.toString)
    if (args(1) == "off") {
        val projected = PostedBoardConfiguration.document(c) ++ Map(
            "profile" -> PlacedTimingProfileBridge.historicalAFields(c),
            "core" -> PlacedTimingProfileBridge.historicalAFields(c.coreParams))
        Files.writeString(out.resolve("published-a-projection.json"), PostedBoardConfiguration.json(projected) + "\n")
    }
}
