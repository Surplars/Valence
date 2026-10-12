package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class EagerPrefixConfigSpec extends AnyFunSuite {
    private val flag = "--eager-fetch-prefix-select"
    private val projectRoot = Iterator.iterate(Paths.get("").toAbsolutePath)(_.getParent)
        .takeWhile(_ != null).find(path => Files.isRegularFile(path.resolve("build.mill"))).get
    private def options(name: String): Seq[String] = {
        val text = Files.readString(projectRoot.resolve("fpga/next/" + name))
        val list = "(?s)\"native_options\"\\s*:\\s*\\[(.*?)\\]".r.findFirstMatchIn(text).get.group(1)
        "\"([^\"]*)\"".r.findAllMatchIn(list).map(_.group(1)).toSeq
    }
    private val base = options("timing-batch-owner-row-profile.json")
    private val off = FpgaNextConfig.fromOptions(base.toSet, defaultSelected = false)
    private val on = FpgaNextConfig.fromOptions((base :+ flag).toSet, defaultSelected = false)

    test("one appended Boolean remains false in every generic and final52 profile") {
        assert(OooParams().productArity == 159 && !OooParams().eagerFetchPrefixSelect)
        assert(OooParams().productElementName(158) == "eagerFetchPrefixSelect")
        for (c <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected, off)) {
            assert(c.productArity == 71 && c.productElementName(70) == "eagerFetchPrefixSelect")
            assert(!c.eagerFetchPrefixSelect && !c.coreParams.eagerFetchPrefixSelect)
            assert(c.coreParams.productArity == 159 && c.cache.productArity == 22 && c.ddr.productArity == 9)
        }
        assert(base.size == 52 && base.distinct.size == 52)
        assert(options("timing-batch-eager-prefix-profile.json") == base :+ flag)
        assert(on.eagerFetchPrefixSelect && on.coreParams.eagerFetchPrefixSelect)
        assert(on.copy(eagerFetchPrefixSelect = false) == off)
        assert(on.coreParams.copy(eagerFetchPrefixSelect = false) == off.coreParams)
        assert(on.ddr == off.ddr && on.cache == off.cache && on.storage == off.storage && on.network == off.network)
        assert(on.issueWidth == 2 && on.coreParams.robEntries == 16 && on.coreParams.physicalRegs == 48 &&
            on.coreParams.memoryEntries == 4 && on.ddr.maxOutstanding == 4 &&
            on.ddr.maxOutstandingWrites == 2 && on.ddr.maxBurstBeats == 16)
    }
    test("Boolean option rejects duplicates values abbreviations and every missing prerequisite") {
        FpgaNextProfileOptions.validate(base :+ flag)
        intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(base ++ Seq(flag, flag)) }
        for (value <- Seq("", "true", "false", "0", "1")) {
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(base :+ (flag + "=" + value)) }
            intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(base.toSet + (flag + "=" + value), false) }
        }
        intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(base :+ flag.dropRight(1)) }
        intercept[IllegalArgumentException] { OooParams(eagerFetchPrefixSelect = true) }
        intercept[IllegalArgumentException] { FpgaNextConfig(eagerFetchPrefixSelect = true) }
        intercept[IllegalArgumentException] { on.copy(alignedFetchPermissionStage = false) }
        intercept[IllegalArgumentException] { on.coreParams.copy(alignedFetchPermissionStage = false) }
        for ((width, compressed, split, aligned) <- Seq((2, true, true, false), (1, true, true, true),
                (2, false, true, true), (2, true, false, true))) {
            intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new RegisteredFetchPacket(width, compressed, BigInt(0),
                    splitCursor = split, alignedPermissionStage = aligned, eagerPrefixSelect = true))
            }
        }
    }
    test("native and GSIM actual constructors select the flag without changing other products") {
        for (c <- Seq(off, on)) {
            var actual = Map.empty[String, Any]
            ChiselStage.emitCHIRRTL {
                val board = c.managedBoard(jtagRamDownload = true)
                actual = EagerPrefixActualAudit.capture(board.platform, c)
                board
            }
            assert(actual == Map("schema" -> "actual-eager-prefix-v1",
                "eagerFetchPrefixSelect" -> c.eagerFetchPrefixSelect,
                "alignedPermissionStage" -> true,
                "selectedPacketEagerPrefixSelect" -> c.eagerFetchPrefixSelect))
            ChiselStage.emitCHIRRTL(FpgaNextBoardGsim.build(c, verifyConfiguration = true))
        }
    }
}
