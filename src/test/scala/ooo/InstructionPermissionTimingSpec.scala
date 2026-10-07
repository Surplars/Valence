package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite

class InstructionPermissionTimingSpec extends AnyFunSuite {
    test("retimed I-fetch keeps PA and permission ownership across the existing send cycle") {
        for (words <- Seq(2, 4); aligned <- Seq(false, true)) {
            val text = ChiselStage.emitCHIRRTL(new InstructionPermissionGsim(words, retimed = true, aligned = aligned))
            assert(text.contains("reg firstPhysical") && text.contains("reg secondPhysical"))
            assert(text.contains("reg secondVirtualPc") && text.contains("regreset permissionCaptured"))
            assert(text.contains("secondPageFault") && text.contains("secondAccessFault"))
            assert(text.contains("checkedAllowed") && text.contains("checkedErrors") && text.contains("checkedPages"))
        }
    }

    test("historical adapter configuration retains its original permission timing") {
        for (words <- Seq(2, 4)) {
            val text = ChiselStage.emitCHIRRTL(new InstructionPermissionGsim(words, retimed = false, aligned = false))
            assert(!text.contains("permissionCaptured") && !text.contains("secondVirtualPc"))
        }
    }
}
