package ooo

import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Current-source constructor checks only; no historical qualification is extended.
  * Reads production objects and adds no DUT ports, state, or observation taps.
  */
object HeadDrainActualAudit {
    def requireShape(c: FpgaNextConfig): Unit = {
        PlacedTimingProfileBridge.requireShape(c)
        require(c.residentMemoryPayloadReuse == c.coreParams.residentMemoryPayloadReuse,
            "profile resident memory payload reuse was not forwarded to the core")
        require(c.postedYoungerLoadSealDeferral == c.coreParams.postedYoungerLoadSealDeferral,
            "profile younger-load seal deferral was not forwarded to the core")
        require(c.retirementIntent == c.coreParams.retirementIntent,
            "profile retirement-intent flag was not forwarded to the core")
        require(c.predecodedHeadDrain == c.coreParams.predecodedHeadDrain,
            "profile head-drain flag was not forwarded to the core")
    }

    def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
        requireShape(expected)
        val core = platform.core.core.core
        val backend = core.backend
        require(core.p == expected.coreParams && backend.p == core.p,
            "actual head-drain core differs from the complete requested profile")
        val rows = backend.headDrainClasses
        require(rows.nonEmpty == expected.predecodedHeadDrain,
            "actual head-drain row presence differs from the requested flag")
        rows.foreach { classes =>
            require(classes.size == core.p.robEntries && classes.forall(_.getWidth == 1),
                "actual head-drain rows must contain one bit per ROB entry")
        }
        Map("schema" -> "actual-head-drain-v1", "predecodedHeadDrain" -> core.p.predecodedHeadDrain,
            "headDrainClassesPresent" -> rows.nonEmpty, "headDrainRows" -> rows.map(_.size).getOrElse(0),
            "headDrainRowBits" -> (if (rows.nonEmpty) 1 else 0),
            "headDrainTotalBits" -> rows.map(_.size).getOrElse(0), "robEntries" -> core.p.robEntries,
            "coreFields" -> core.p.productArity, "profileFields" -> expected.productArity)
    }

    def write(actual: Map[String, Any], directory: String): Unit = {
        Files.createDirectories(Paths.get(directory))
        Files.writeString(Paths.get(directory, "actual-head-drain.json"), PostedBoardConfiguration.json(actual) + "\n")
    }
}
