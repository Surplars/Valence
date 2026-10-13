package ooo

import soc.core.ooo._

/** Inspect the constructed Home, not a profile copy. No DUT ports or state. */
object FutureHomeActualAudit {
    def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
        val home = platform.finalHome.getOrElse(
            throw new IllegalArgumentException("actual final Home absent")) match {
            case mixed: MixedCoherentLineHome => mixed
            case _ => throw new IllegalArgumentException("actual final Home must be bounded mixed")
        }
        require(home.futureWayReservation == expected.futureHomeWayReservation &&
            home.futureWayReservation == expected.cache.futureHomeWayReservation,
            "actual final Home future reservation forwarding differs")
        require(home.memoryScheduleOverlap == expected.memoryScheduleOverlap,
            "actual final Home overlap forwarding differs")
        Map("schema" -> "actual-future-home-way-v1",
            "futureHomeWayReservation" -> home.futureWayReservation,
            "memoryScheduleOverlap" -> home.memoryScheduleOverlap,
            "homeClass" -> home.getClass.getName)
    }
}
