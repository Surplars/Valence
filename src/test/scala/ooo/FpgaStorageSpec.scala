package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class FpgaStorageSpec extends AnyFunSuite {
    test("FPGA storage options preserve the selected dimensions and are explicit") {
        val base = BoardSocConfig.timingParams("staged-fetch-turnover")
        assert(base.robEntries == 16 && base.physicalRegs == 48 && base.memoryEntries == 2)
        assert(!base.bankedRobPayload && !base.sharedStoreOperandReads)
        val selected = base.copy(bankedRobPayload = true, sharedStoreOperandReads = true)
        assert(selected.copy(bankedRobPayload = false, sharedStoreOperandReads = false) == base)
        intercept[IllegalArgumentException] { OooParams(sharedStoreOperandReads = true) }
        intercept[IllegalArgumentException] { OooParams(renameWidth = 4, bankedRobPayload = true) }
    }
    test("production storage parser composes with other keyed arguments") {
        val (remaining, storage) = FpgaStorageConfig.parseArgs(Array("out", "--compact-tags",
            "--banked-rob", "--network-rx-slots=4", "--shared-store-reads", "--identity-data-flow"))
        assert(storage == FpgaStorageConfig.BankedShared)
        assert(remaining.toSeq == Seq("out", "--compact-tags", "--network-rx-slots=4", "--identity-data-flow"))
        val selected = BoardSocConfig.boardParams("staged-fetch-turnover", fpgaStorage = storage)
        assert(selected.bankedRobPayload && selected.sharedStoreOperandReads && selected.issueWidth == 2)
        intercept[IllegalArgumentException] {
            BoardSocConfig.boardParams("baseline", width = 4, fpgaStorage = storage)
        }
        intercept[IllegalArgumentException] {
            BoardSocConfig.boardParams("baseline", fpgaStorage = FpgaStorageConfig(sharedStoreOperandReads = true))
        }
        intercept[IllegalArgumentException] { FpgaStorageConfig.parseArgs(Array("--banked-rob", "--banked-rob")) }
    }
    test("ROB allocation payload has two asynchronous single-write banks") {
        val fir = ChiselStage.emitCHIRRTL(new BankedRobPayload(16))
        assert("cmem".r.findAllIn(fir).length == 2, fir)
        assert(!fir.contains("smem"), "no synchronous-read latency may be introduced")
        assert(fir.contains("UInt<96>[8]"), fir)
    }
    test("both ROB storage modes elaborate") {
        for (enabled <- Seq(false, true)) {
            val fir = ChiselStage.emitCHIRRTL(new RenameRob(OooParams(
                robEntries = 16, physicalRegs = 48, recoveryWidth = 4, bankedRobPayload = enabled)))
            assert(fir.contains("module RenameRob"))
            assert(fir.contains("module BankedRobPayload") == enabled)
        }
    }
}
