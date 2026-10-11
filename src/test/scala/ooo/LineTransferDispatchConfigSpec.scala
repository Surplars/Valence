package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.TLParams
import soc.core.ooo._
import soc.ip.tilelink.{TileLinkLineFillEngine, TileLinkLineWriteEngine}

class LineTransferDispatchConfigSpec extends AnyFunSuite {
    test("dispatch flow is independent of DDR collection and frozen performance geometry") {
        for (base <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected);
            writeFlow <- Seq(false, true)) {
            val off = base.copy(ddrWriteCollectionFlow = writeFlow)
            assert(!off.lineTransferDispatchFlow)
            val on = off.copy(lineTransferDispatchFlow = true)
            assert(on.coreParams == off.coreParams && on.ddr == off.ddr && on.cache == off.cache)
            assert(on.network == off.network && on.name == off.name + "-line-transfer-dispatch-flow")
        }
        val selected = FpgaNextConfig.fromOptions(Set("--selected", "--line-transfer-dispatch-flow"), true)
        assert(selected == FpgaNextConfig.Selected.copy(lineTransferDispatchFlow = true))
        intercept[IllegalArgumentException] {
            FpgaNextConfig.fromOptions(Set("--line-transfer-dispatch-flow=false"), true)
        }
    }

    test("engine dispatch bypass adds no line owner or payload capacity") {
        val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
        for (flow <- Seq(false, true); entries <- Seq(2, 4, 8)) {
            val reader = ChiselStage.emitCHIRRTL(new TileLinkLineFillEngine(params, entries, dispatchFlow = flow))
            val writer = ChiselStage.emitCHIRRTL(new TileLinkLineWriteEngine(params, entries, dispatchFlow = flow))
            assert(reader.contains("module TileLinkLineFillEngine"))
            assert(writer.contains("module TileLinkLineWriteEngine") && writer.contains("activeData"))
            assert(reader.contains(s"phase : UInt<2>[$entries]") &&
                writer.contains(s"phase : UInt<2>[$entries]"))
        }
    }
}
