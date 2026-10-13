package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Pure configuration/source compatibility. Does not extend component qualification to a CPU/board. */
class PlacedTimingConfigSpec extends AnyFunSuite {
    private def fields(p: Product): Map[String, Any] = p.productElementNames.zip(p.productIterator).toMap
    private def changes(before: Product, after: Product): Map[String, Any] =
        fields(after).filter { case (name, value) => fields(before)(name) != value }
    test("published default52 values and field order survive only the explicit false additions") {
        val off = PlacedTimingProfile.off
        PlacedTimingProfile.requireExact(off)
        assert(PlacedTimingProfile.defaultOptions.size == 52)
        for (c <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.FetchCaptureCandidate,
                FpgaNextConfig.TriSpeedCandidate, FpgaNextConfig.ControlCandidate, FpgaNextConfig.Selected,
                FpgaNextConfig.RegisteredPmpCandidate, off)) {
            PlacedTimingProfileBridge.requireShape(c)
            PlacedTimingProfileBridge.publishedFields(c)
            PlacedTimingProfileBridge.publishedFields(c.coreParams)
            assert(!c.predecodedHeadDrain && !c.retirementIntent)
        }
        assert(PlacedTimingProfileBridge.coreAdditions.forall(n => fields(OooParams())(n) == false))
    }
    test("component and complete ON profiles change exactly their named fields") {
        val off = PlacedTimingProfile.off
        val component = PlacedTimingProfile.component
        val on = PlacedTimingProfile.on
        for (c <- Seq(component, on)) PlacedTimingProfile.requireExact(c)
        val timingProfile = Seq("fetchAddressBeforePmp", "queuedHeadSelection", "alignedNextLinePmp",
            "registerProbeLookup", "localAddressRanges").map(_ -> true).toMap
        val timingCore = Seq("fetchAddressBeforePmp", "queuedHeadSelection", "alignedNextLinePmp").map(_ -> true).toMap
        assert(changes(off, component) == timingProfile)
        assert(changes(off.coreParams, component.coreParams) == timingCore)
        val existing = Map("predecodedHeadDrain" -> true, "retirementIntent" -> true)
        assert(changes(off, on) == timingProfile ++ existing)
        assert(changes(off.coreParams, on.coreParams) == timingCore ++ existing)
        for (c <- Seq(component, on)) {
            assert(c.cache == off.cache && c.ddr == off.ddr && c.storage == off.storage && c.tags == off.tags &&
                c.network == off.network && c.floatingPointResources == off.floatingPointResources)
            intercept[IllegalArgumentException] { PlacedTimingProfileBridge.publishedFields(c) }
            intercept[IllegalArgumentException] { PlacedTimingProfileBridge.publishedFields(c.coreParams) }
        }
    }
    test("new options reject duplicate valued unknown and unsupported source selections") {
        val base = PlacedTimingProfile.defaultOptions
        for (flag <- PlacedTimingProfile.timingOptions) {
            FpgaNextProfileOptions.validate(base :+ flag)
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(base ++ Seq(flag, flag)) }
            for (value <- Seq("", "true", "false", "0", "1")) {
                intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(base :+ (flag + "=" + value)) }
                intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(base.toSet + (flag + "=" + value), false) }
            }
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(base :+ (flag + "s")) }
        }
        intercept[IllegalArgumentException] { OooParams(fetchAddressBeforePmp = true) }
        intercept[IllegalArgumentException] { OooParams(queuedHeadSelection = true) }
        intercept[IllegalArgumentException] { OooParams(alignedNextLinePmp = true) }
        intercept[IllegalArgumentException] { FpgaNextConfig(queuedHeadSelection = true) }
        intercept[IllegalArgumentException] { FpgaNextConfig(fetchAddressBeforePmp = true) }
    }
}
