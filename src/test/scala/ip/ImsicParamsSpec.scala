package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.interrupt._

class ImsicParamsSpec extends AnyFunSuite {
    test("IMSIC geometry rejects aliases, invalid identity counts and overflowing windows") {
        for (n <- Seq(0, 62, 64, 2048)) intercept[IllegalArgumentException] { ImsicParams(identities = n) }
        for (g <- Seq(-1, 64)) intercept[IllegalArgumentException] { ImsicParams(guestFiles = g) }
        intercept[IllegalArgumentException] { ImsicParams(machineBase = 1) }
        intercept[IllegalArgumentException] { ImsicParams(supervisorBase = BigInt("24000000", 16)) }
        intercept[IllegalArgumentException] { ImsicParams(guestFiles = 2, supervisorBase = 4096) }
        intercept[IllegalArgumentException] { ImsicParams(machineBase = BigInt(1) << 64) }
        assert(ImsicParams(guestFiles = 2).supervisorPages == 4)
    }
    test("standalone IMSIC has no CPU dependency and supports maximum file topology") {
        val rtl = ChiselStage.emitCHIRRTL(new Imsic(ImsicParams(identities = 63, guestFiles = 63)))
        assert(rtl.contains("module Imsic") && !rtl.contains("IntegerBackend"))
    }
}
