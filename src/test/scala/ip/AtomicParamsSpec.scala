package ip

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.memory.AtomicMemory

class AtomicParamsSpec extends AnyFunSuite {
    test("ordinary response ownership can be registered without changing the atomic port") {
        val rtl = ChiselStage.emitCHIRRTL(new AtomicMemory(registerResponseOwners = true))
        assert(rtl.contains("module AtomicMemory"))
        assert(rtl.contains("module Queue8_Bool"))
        assert(rtl.contains("clearReservation"))
    }
    test("atomic RAM window respects reservation granules and 64-bit address bounds") {
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new AtomicMemory(base = 8)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new AtomicMemory(bytes = 65)) }
        intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new AtomicMemory(base = (BigInt(1) << 64) - 64)) }
        val rtl = ChiselStage.emitCHIRRTL(new AtomicMemory(base = 0x1000, bytes = 64))
        assert(rtl.contains("module AtomicMemory"))
    }
}
