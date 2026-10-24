package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class CircularFetchStorageSpec extends AnyFunSuite {
    test("circular storage is explicit and the legacy reservoir remains the default") {
        val legacy = ChiselStage.emitCHIRRTL(new RegisteredFetchPacket(2, true, BigInt("80000000", 16)))
        assert(!legacy.contains("module CircularFetchInstructionStorage"))
        val candidate = ChiselStage.emitCHIRRTL(new RegisteredFetchPacket(2, true, BigInt("80000000", 16),
            circularPayload = true))
        assert(candidate.contains("module CircularFetchInstructionStorage"))
        assert(candidate.contains("lookaheadPc"))
    }
    test("circular specialization rejects wider and optional phase-token modes") {
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new RegisteredFetchPacket(4, true, BigInt("80000000", 16),
                circularPayload = true))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new RegisteredFetchPacket(2, true, BigInt("80000000", 16),
                splitCursor = true, alignedPermissionStage = true, circularPayload = true))
        }
    }
}
