package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.ip.tilelink.TwoMasterTileLinkArbiter

class FetchControlTimingSpec extends AnyFunSuite {
    test("fetch control candidate combines related feedback cuts without widening or changing defaults") {
        val p = BoardSocConfig.timingParams("staged-fetch-control")
        assert(p == BoardSocConfig.timingParams("staged-fetch-address").copy(
            rawTileLinkResponseMetadata = true, bufferedRomReplies = true, parallelPredictionQualification = true))
        assert(p.issueWidth == 2 && p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 2)
        assert(!OooParams().rawTileLinkResponseMetadata && !OooParams().bufferedRomReplies &&
            !OooParams().parallelPredictionQualification && BoardSocConfig.timingProfile == "early-issue")
        intercept[IllegalArgumentException] { BoardSocConfig.timingParams("staged-fetch-control", 4) }
    }
    test("direct prediction guard is combinational and uses only low-bit address addition") {
        val fir = ChiselStage.emitCHIRRTL(new DirectPredictionQualification)
        assert(!fir.linesIterator.exists(_.trim.matches("reg(reset)? .*")))
        assert(fir.contains("bits(io.immediate, 1, 0)"))
        assert(!fir.contains("add(io.immediate"))
    }
    test("raw reply lookup preserves all ownership and burst state") {
        val modes = Seq(false, true).map(raw => ChiselStage.emitCHIRRTL(
            new TwoMasterTileLinkArbiter(rawResponseMetadata = raw)))
        def registers(fir: String): Int = fir.linesIterator.count(_.trim.matches("reg(reset)? .*"))
        assert(registers(modes.head) == registers(modes(1)))
        assert(modes.head.contains("mux(io.manager.d.valid"))
        assert(!modes(1).contains("mux(io.manager.d.valid"))
    }
    test("ROM reply credits use a separate two-entry queue, not a default behavior change") {
        val old = ChiselStage.emitCHIRRTL(new TileLinkInstructionRomAdapter(2048))
        val buffered = ChiselStage.emitCHIRRTL(new TileLinkInstructionRomAdapter(2048, bufferedReplies = true))
        assert(!old.contains("inst produced_replies of Queue2_TLBundleD"))
        assert(buffered.contains("inst produced_replies of Queue2_TLBundleD"))
        for (p <- Seq(OooParams(rawTileLinkResponseMetadata = true), OooParams(bufferedRomReplies = true))) {
            intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new MachinePlatform(p)) }
        }
    }
}
