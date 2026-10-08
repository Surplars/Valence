package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class FpgaIssueStorageSpec extends AnyFunSuite {
    test("issue and hint RAM choices are opt-in and preserve geometry") {
        val base = BoardSocConfig.timingParams("staged-fetch-turnover")
        assert(!base.bankedIssuePayload && !base.bankedFetchHints)
        val (args, config) = FpgaStorageConfig.parseArgs(Array("out", "--banked-issue-payload", "--banked-fetch-hints"))
        assert(args.toSeq == Seq("out") && config.bankedIssuePayload && config.bankedFetchHints)
        assert(config.configure(base).copy(bankedIssuePayload = false, bankedFetchHints = false) == base)
        intercept[IllegalArgumentException] { OooParams(renameWidth = 4, bankedIssuePayload = true) }
        intercept[IllegalArgumentException] { OooParams(bankedFetchHints = true) }
        intercept[IllegalArgumentException] {
            FpgaStorageConfig.parseArgs(Array("--banked-fetch-hints", "--banked-fetch-hints"))
        }
    }
    test("issue fields have two parity banks and only their explicit asynchronous readers") {
        val fir = ChiselStage.emitCHIRRTL(new BankedIssuePayload(16, BankedIssuePayloadTestConfig.fields))
        assert("cmem".r.findAllIn(fir).length == 12, fir)
        assert("write mport".r.findAllIn(fir).length == 12, fir)
        assert("read mport".r.findAllIn(fir).length == 36, fir)
        assert(!fir.contains("smem"), "no hidden synchronous-read stage")
        assert(fir.contains("UInt<64>[8]") && fir.contains("UInt<32>[8]"), fir)
    }
    test("unneeded fields do not create memory banks") {
        val fir = ChiselStage.emitCHIRRTL(new BankedIssuePayload(16, Seq(Set("pc"), Set("immediate"))))
        assert("cmem".r.findAllIn(fir).length == 4, fir)
        assert("read mport".r.findAllIn(fir).length == 4, fir)
    }
    test("hint bank count follows writer lanes, not address parity") {
        for (lanes <- Seq(1, 2, 4)) {
            val fir = ChiselStage.emitCHIRRTL(new OwnerBankedFetchHints(32, lanes))
            assert("cmem".r.findAllIn(fir).length == lanes, fir)
            assert("write mport".r.findAllIn(fir).length == lanes, fir)
            assert("read mport".r.findAllIn(fir).length == lanes * lanes, fir)
            assert(fir.contains("UInt<162>[32]") && !fir.contains("smem"), fir)
        }
    }
}
