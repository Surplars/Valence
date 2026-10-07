package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class FetchFeedbackTimingSpec extends AnyFunSuite {
    test("permission, cursor and registered cache window remain opt-in with independent ISA selection") {
        val before = BoardSocConfig.timingParams("staged-ethernet")
        val next = BoardSocConfig.timingParams("staged-fetch-feedback")
        assert(next == before.copy(capturedFetchPermission = true, splitFetchCursor = true,
            registeredFetchWindow = true))
        assert(next.renameWidth == 2 && next.commitWidth == 2 && !next.fpEnabled)
        assert(!OooParams().capturedFetchPermission && !OooParams().splitFetchCursor &&
            !OooParams().registeredFetchWindow)
        assert(BoardSocConfig.timingProfile == "early-issue" && BoardSocConfig.isaProfile == "rv64imac")
        for (isa <- BoardSocConfig.isaProfiles) {
            val p = BoardSocConfig.boardParams("staged-fetch-feedback", externalDdr = true, isa = isa)
            assert(p.capturedFetchPermission && p.registeredFetchWindow && p.pmpEntries == 16)
            assert(p.fpConfig.f == (isa != "rv64imac") && p.fpConfig.d == (isa == "rv64gc"))
        }
    }
    test("permission captured before reservoir; corrected and normal PC banks are separately registered") {
        val p = BoardSocConfig.boardParams("staged-fetch-feedback", externalDdr = true)
        val text = ChiselStage.emitCHIRRTL(new IntegerCore(p))
        assert(text.contains("module FetchPacketPermission"))
        assert(text.contains("regreset rawCursor") && text.contains("reg correctionPc") &&
            text.contains("regreset correctionPending"))
        assert(text.contains("connect permission.io.base, fetchPacket.io.fetchPc"))
        // Architectural-PC PMP must no longer be instantiated after capture.
        assert(!text.contains("inst packetPmp of PacketFetchPmp"))
    }
    test("illegal partial configurations cannot silently snapshot permissions") {
        intercept[IllegalArgumentException](OooParams(capturedFetchPermission = true))
        intercept[IllegalArgumentException](OooParams(splitFetchCursor = true))
    }
}
