package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class OwnerBankedPrfSpec extends AnyFunSuite {
    test("owner-banked PRF uses explicit asynchronous data memories") {
        for (entries <- Seq(48, 64, 128, 256)) {
            val fir = ChiselStage.emitCHIRRTL(new OwnerBankedPhysicalRegisterFile(entries, 4))
            assert("cmem".r.findAllIn(fir).length == 2, fir)
            assert(!fir.contains("smem"), "same-cycle asynchronous read contract")
            assert(fir.contains(s"UInt<64>[$entries]"), fir)
        }
    }
    test("PRF topology is opt-in and rejects the third writer") {
        val base = BoardSocConfig.boardParams("staged-fetch-turnover", isa = "rv64gc")
        val (args, storage) = FpgaStorageConfig.parseArgs(Array("out", "--lvt-prf", "--compact-tags"))
        assert(args.toSeq == Seq("out", "--compact-tags"))
        assert(!base.lvtPhysicalRegisterFile && !base.fastHeadLoadRetire)
        val p = storage.configure(base)
        assert(p.lvtPhysicalRegisterFile && p.physicalRegs == 48 && p.memoryEntries == 2)
        intercept[IllegalArgumentException] { OooParams(lvtPhysicalRegisterFile = true, fastHeadLoadRetire = true) }
        intercept[IllegalArgumentException] { OooParams(lvtPhysicalRegisterFile = true, completionWidth = 4) }
        intercept[IllegalArgumentException] { FpgaStorageConfig.parseArgs(Array("--lvt-prf", "--lvt-prf")) }
    }
}
