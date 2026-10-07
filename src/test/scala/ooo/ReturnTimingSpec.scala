package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class ReturnTimingSpec extends AnyFunSuite {
    test("return candidate batches physical operands and registered/direct replies without widening") {
        val p = BoardSocConfig.timingParams("staged-return")
        assert(p == BoardSocConfig.timingParams("staged-payload").copy(oneHotPhysicalOperands = true,
            registeredTranslatedResponses = true, directMemoryResponse = true))
        assert(p.issueWidth == 2 && p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 2)
        assert(BoardSocConfig.timingProfile == "early-issue")
        intercept[IllegalArgumentException] { OooParams(oneHotPhysicalOperands = true) }
        intercept[IllegalArgumentException] { p.copy(loadCompletionBypass = true) }
        intercept[IllegalArgumentException] { p.copy(mulWordPreviewBypass = true) }
        intercept[IllegalArgumentException] { BoardSocConfig.timingParams("staged-return", 4) }
    }
    test("physical operand reads have no state or dynamic PRF indexing") {
        for ((entries, registers) <- Seq((16, 48), (32, 64))) {
            val rtl = ChiselStage.emitCHIRRTL(new IssuePhysicalOperands(OooParams(
                robEntries = entries, physicalRegs = registers)))
            assert(rtl.contains("module IssuePhysicalOperands"))
            assert(!rtl.linesIterator.exists(_.trim.startsWith("reg ")) && !rtl.contains("subaccess("))
        }
    }
    test("registered translated replies cannot silently bypass or stack outside their boundary") {
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new MappedMachineCore(OooParams(registeredTranslatedResponses = true)))
        }
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new MappedMachineCore(OooParams(directMemoryResponse = true)))
        }
        for (registered <- Seq(false, true)) {
            val rtl = ChiselStage.emitCHIRRTL(new DataTimingGsim(registerPayload = registered))
            assert(rtl.contains("module DataResponseBuffer"))
        }
        val fabric = ChiselStage.emitCHIRRTL(new StagedFabricGsim(bypassMemoryShift = true))
        assert(fabric.contains("localData") && fabric.contains("localShift"))
    }
}
