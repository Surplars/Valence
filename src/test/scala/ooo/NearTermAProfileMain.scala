package ooo

import java.nio.file.{Files, Paths}

/** Constructor-only report, with no hardware elaboration or model build. */
object NearTermAProfileMain extends App {
    require(args.length == 2, "usage: NearTermAProfileMain fresh-directory rollback|on")
    val c = args(1) match {
        case "rollback" => NearTermAProfile.rollback
        case "on" => NearTermAProfile.on
        case _ => throw new IllegalArgumentException("choose rollback or on")
    }
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh constructor report required")
    PostedBoardConfiguration.write(c, out.toString)
    Files.writeString(out.resolve("near-term-a-source-bridge.json"),
        PostedBoardConfiguration.json(NearTermAProfile.sourceBridge) + "\n")
}
