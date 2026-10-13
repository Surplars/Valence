package ooo

import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Elaboration-only inspection of the production leaves selected by the unified
  * profile. No new DUT port, register, event tap, or hardware state is introduced.
  */
object PlacedTimingActualAudit {
    def capture(platform: MachinePlatform, expected: FpgaNextConfig): Map[String, Any] = {
        PlacedTimingProfileBridge.requireShape(expected)
        require(platform.core.core.core.p == expected.coreParams,
            "actual core differs from the complete placed-timing profile")
        val frontend = platform.frontend
        val adapter = platform.core.observationTranslation.getOrElse(
            throw new IllegalArgumentException("actual data translation adapter was not constructed"))
        val hint = adapter.nextLineAuthorizationInstance.getOrElse(
            throw new IllegalArgumentException("actual next-line authorization was not constructed"))
        val cache = platform.privateCache.get match {
            case c: NonBlockingCoherentLineCache => c
            case _ => throw new IllegalArgumentException("actual private cache is not the nonblocking implementation")
        }
        val wrapper = platform.ddrManagerInstance.getOrElse(
            throw new IllegalArgumentException("actual external DDR manager was not constructed"))
        val manager = wrapper.outstandingInstance.getOrElse(
            throw new IllegalArgumentException("actual outstanding DDR manager was not constructed"))
        require(frontend.fetchAddressBeforePmp == expected.fetchAddressBeforePmp,
            "actual frontend address stage differs from the requested flag")
        require(adapter.queuedHeadSelection == expected.queuedHeadSelection &&
            adapter.alignedNextLinePmp == expected.alignedNextLinePmp,
            "actual adapter local selections differ from the requested flags")
        require(hint.alignedLinePmp == expected.alignedNextLinePmp &&
            hint.checker.alignedLineAccess == expected.alignedNextLinePmp,
            "actual hint module or nested PMP checker did not receive the aligned-line flag")
        require(cache.registerProbeLookup == expected.registerProbeLookup,
            "actual nonblocking cache did not receive the registered probe flag")
        require(wrapper.localAddressRanges == expected.localAddressRanges &&
            manager.localAddressRanges == expected.localAddressRanges &&
            manager.slots.size == expected.ddr.maxOutstanding &&
            manager.slots.forall(_.localAddressRanges == expected.localAddressRanges),
            "actual DDR wrapper, manager, or burst slot did not receive the local-range flag")
        Map("schema" -> "actual-placed-timing-v1", "scope" -> "actual-constructor-only",
            "frontendClass" -> frontend.getClass.getName,
            "fetchAddressBeforePmp" -> frontend.fetchAddressBeforePmp,
            "adapterClass" -> adapter.getClass.getName, "queuedHeadSelection" -> adapter.queuedHeadSelection,
            "alignedNextLinePmp" -> adapter.alignedNextLinePmp,
            "hintClass" -> hint.getClass.getName, "hintAlignedLinePmp" -> hint.alignedLinePmp,
            "checkerClass" -> hint.checker.getClass.getName,
            "checkerAlignedLineAccess" -> hint.checker.alignedLineAccess,
            "cacheClass" -> cache.getClass.getName, "registerProbeLookup" -> cache.registerProbeLookup,
            "wrapperClass" -> wrapper.getClass.getName, "wrapperLocalAddressRanges" -> wrapper.localAddressRanges,
            "managerClass" -> manager.getClass.getName, "managerLocalAddressRanges" -> manager.localAddressRanges,
            "slotCount" -> manager.slots.size,
            "slotLocalAddressRanges" -> manager.slots.map(_.localAddressRanges),
            "headDrain" -> HeadDrainActualAudit.capture(platform, expected),
            "retirementIntent" -> RetirementIntentActualAudit.capture(platform, expected),
            "dynamicQualificationInherited" -> false, "physicalQualification" -> false)
    }
    def write(actual: Map[String, Any], directory: String): Unit = {
        Files.createDirectories(Paths.get(directory))
        Files.writeString(Paths.get(directory, "actual-placed-timing.json"),
            PostedBoardConfiguration.json(actual) + "\n")
    }
}
