package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.bus.tilelink.TLParams
import soc.ip.bus.TwoEntryRegisterQueue
import soc.ip.tilelink.RegisteredTileLinkBoundary
import chisel3._

class RomBoundaryTimingSpec extends AnyFunSuite {
    test("ROM boundary inherits the two-issue geometry and stays opt-in") {
        val prior = BoardSocConfig.timingParams("staged-request-capture")
        val next = BoardSocConfig.timingParams("staged-rom-boundary")
        assert(next == prior.copy(registeredFabricBoundary = true))
        assert(next.renameWidth == 2 && next.robEntries == 16 && next.physicalRegs == 48)
        assert(!OooParams().registeredFabricBoundary)
        intercept[IllegalArgumentException](OooParams(registeredFabricBoundary = true))
    }
    test("registered head has two slots and no memory read port") {
        val fir = ChiselStage.emitCHIRRTL(new TwoEntryRegisterQueue(UInt(64.W)))
        assert(fir.contains("headValid") && fir.contains("tailValid"))
        assert(!fir.contains("smem ") && !fir.contains("cmem "))
        val request = ChiselStage.emitCHIRRTL(new DataRequestBuffer(registerHead = true))
        assert(request.contains("TwoEntryRegisterQueue") && !request.contains("module Queue"))
        intercept[IllegalArgumentException] {
            ChiselStage.emitCHIRRTL(new DataRequestBuffer(4, registerHead = true))
        }
    }
    test("TL boundary retains A and D payloads in independent registered slots") {
        val fir = ChiselStage.emitCHIRRTL(new RegisteredTileLinkBoundary(TLParams(addrWidth = 64)))
        assert(fir.contains("requests") && fir.contains("replies"))
        assert(!fir.contains("smem ") && !fir.contains("cmem "))
    }
}
