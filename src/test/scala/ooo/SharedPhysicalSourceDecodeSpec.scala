package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite

class SharedPhysicalSourceDecodeSpec extends AnyFunSuite {
    test("one pure source decode drives three independent early read clients without state") {
        for ((entries, registers) <- Seq((16, 48), (32, 64))) {
            val rtl = ChiselStage.emitCHIRRTL(new PhysicalOperandsGsim(entries, registers,
                sharedDecode = true, clients = 3))
            val decoders = """(?m)^\s*inst \S+ of QueuedPhysicalSourceDecode\b""".r.findAllIn(rtl).size
            val readers = """(?m)^\s*inst \S+ of IssuePhysicalOperands(?:_\d+)?\b""".r.findAllIn(rtl).size
            assert(decoders == 1 && readers == 3)
            assert("""(?m)^\s*(reg|regreset)\s""".r.findFirstIn(rtl).isEmpty)
        }
    }
    test("default standalone interface and local decode remain available") {
        val rtl = ChiselStage.emitCHIRRTL(new PhysicalOperandsGsim(16, 48))
        assert(!rtl.contains("QueuedPhysicalSourceDecode"))
        assert(!rtl.contains("otherOwners") && !rtl.contains("decoded1"))
    }
}
