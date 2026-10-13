package ooo

import java.nio.file.{Files, Paths}

/** Constructor-only reports; neither branch elaborates or runs a DUT. */
object R3ReadLocalityProfileMain extends App {
    require(args.length == 2, "usage: R3ReadLocalityProfileMain fresh-directory off|on")
    val c = args(1) match {
        case "off" => R3ReadLocalityProfile.off
        case "on" => R3ReadLocalityProfile.on
        case _ => throw new IllegalArgumentException("choose constructor-only off or on")
    }
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh constructor profile directory required")
    PostedBoardConfiguration.write(c, out.toString)
    Files.writeString(out.resolve("r3-source-bridge.json"),
        PostedBoardConfiguration.json(R3ReadLocalityProfile.sourceBridge) + "\n")
}
