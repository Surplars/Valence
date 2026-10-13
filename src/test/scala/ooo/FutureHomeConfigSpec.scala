package ooo

import java.nio.file.{Files, Paths}
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class FutureHomeConfigSpec extends AnyFunSuite {
    private val flag = "--future-home-way-reservation"
    private val projectRoot = Iterator.iterate(Paths.get("").toAbsolutePath)(_.getParent)
        .takeWhile(_ != null).find(path => Files.isRegularFile(path.resolve("build.mill"))).get
    private val text = Files.readString(projectRoot.resolve("fpga/next/timing-batch-owner-row-profile.json"))
    private val list = "(?s)\"native_options\"\\s*:\\s*\\[(.*?)\\]".r.findFirstMatchIn(text).get.group(1)
    private val base = "\"([^\"]*)\"".r.findAllMatchIn(list).map(_.group(1)).toSeq
    private val off = FpgaNextConfig.fromOptions(base.toSet, false)
    private val on = FpgaNextConfig.fromOptions(base.toSet + flag, false)

    test("one default-false Home flag preserves exact final52 resources and core") {
        assert(base.size == 52 && base.distinct.size == 52)
        for (c <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected, off)) {
            assert(c.productArity == 72 && c.productElementName(71) == "futureHomeWayReservation")
            assert(c.cache.productArity == 23 && c.cache.productElementName(22) == "futureHomeWayReservation")
            assert(!c.futureHomeWayReservation && !c.cache.futureHomeWayReservation)
            assert(!c.eagerFetchPrefixSelect && !c.coreParams.eagerFetchPrefixSelect)
        }
        assert(on.futureHomeWayReservation && on.cache.futureHomeWayReservation)
        assert(on.copy(futureHomeWayReservation = false) == off)
        assert(on.cache.copy(futureHomeWayReservation = false) == off.cache)
        assert(on.coreParams == off.coreParams && on.ddr == off.ddr && on.storage == off.storage && on.network == off.network)
        assert(on.coreParams.productArity == 159 && on.ddr.productArity == 9)
        assert(on.issueWidth == 2 && on.cpuHz == 100000000 && on.coreParams.robEntries == 16 &&
            on.coreParams.physicalRegs == 48 && on.coreParams.memoryEntries == 4 &&
            on.cache.readMshrs == 2 && on.cache.writebackEntries == 2 && on.cache.responseEntries == 2 &&
            on.ddr.maxOutstanding == 4 && on.ddr.maxOutstandingWrites == 2 && on.ddr.maxBurstBeats == 16)
    }
    test("Boolean spelling, duplicate and prerequisite checks fail closed") {
        FpgaNextProfileOptions.validate(base :+ flag)
        intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(base ++ Seq(flag, flag)) }
        for (value <- Seq("", "true", "false", "0", "1")) {
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(base :+ (flag + "=" + value)) }
            intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(base.toSet + (flag + "=" + value), false) }
        }
        intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(base :+ flag.dropRight(1)) }
        intercept[IllegalArgumentException] { FpgaNextConfig(futureHomeWayReservation = true) }
        intercept[IllegalArgumentException] { CoherentCacheConcurrency(futureHomeWayReservation = true) }
        intercept[IllegalArgumentException] { on.copy(memoryScheduleOverlap = false) }
        intercept[IllegalArgumentException] { on.cache.copy(memoryScheduleOverlap = false) }
        intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(base.toSet - "--memory-schedule-overlap" + flag, false) }
    }
}
