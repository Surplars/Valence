package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class OwnerBankedPrfSpec extends AnyFunSuite {
    test("owner-banked PRF uses explicit asynchronous data memories") {
        for (entries <- Seq(33, 48, 63, 64, 65, 127, 128, 129, 255, 256)) {
            val fir = ChiselStage.emitCHIRRTL(new OwnerBankedPhysicalRegisterFile(entries, 4))
            assert("cmem".r.findAllIn(fir).length == 2, fir)
            assert(!fir.contains("smem"), "same-cycle asynchronous read contract")
            assert(fir.contains(s"UInt<64>[$entries]"), fir)
        }
    }
    test("compact read aliases stay in bounds and preserve every valid address") {
        for (entries <- 33 to 256) {
            val addressSpace = Integer.highestOneBit(entries - 1) << 1
            val lowMask = addressSpace / 2 - 1
            for (address <- 0 until addressSpace) {
                val inRange = address < entries
                val safe = if (inRange) address else address & lowMask
                assert(safe >= 0 && safe < entries)
                assert(!inRange || safe == address)
                assert((safe & lowMask) == (address & lowMask))
            }
        }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new OwnerBankedPhysicalRegisterFile(32, 1)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new OwnerBankedPhysicalRegisterFile(257, 1)) }
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
