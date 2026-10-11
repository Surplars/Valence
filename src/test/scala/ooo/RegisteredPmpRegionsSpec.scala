package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class RegisteredPmpRegionsSpec extends AnyFunSuite {
    test("atomic PMP publication is explicit and retains the frozen board presets") {
        val base = FpgaNextConfig.Selected
        assert(!OooParams().registeredPmpRegions)
        assert(!base.registeredPmpRegions && !base.coreParams.registeredPmpRegions)
        val selected = FpgaNextConfig.fromOptions(Set("--selected", "--registered-pmp-regions"), true)
        assert(selected == FpgaNextConfig.RegisteredPmpCandidate)
        assert(selected.copy(registeredPmpRegions = false) == base)
        assert(selected.coreParams.copy(registeredPmpRegions = false) == base.coreParams)
        assert(selected.name == base.name + "-registered-pmp-regions")
        assert(selected.cache == base.cache && selected.ddr == base.ddr && selected.network == base.network)
        intercept[IllegalArgumentException] {
            FpgaNextConfig.fromOptions(Set("--registered-pmp-regions=false"), true)
        }
    }

    test("only implemented machine PMP configurations may register ranges") {
        for (entries <- Seq(0, 8, 16)) {
            val base = OooParams(machineSystem = true, pmpEntries = entries)
            assert(!base.registeredPmpRegions)
            if (entries == 0) intercept[IllegalArgumentException] { base.copy(registeredPmpRegions = true) }
            else assert(base.copy(registeredPmpRegions = true).copy(registeredPmpRegions = false) == base)
        }
        intercept[IllegalArgumentException] { OooParams(registeredPmpRegions = true) }
        intercept[IllegalArgumentException] { OooParams(pmpEntries = 8, registeredPmpRegions = true) }
        intercept[IllegalArgumentException] {
            OooParams(machineSystem = true, pmpEntries = 4, registeredPmpRegions = true)
        }
    }

    test("the actual machine CSR unit registers only implemented bounds") {
        for (entries <- Seq(8, 16); selected <- Seq(false, true)) {
            val fir = ChiselStage.emitCHIRRTL(new MachineSystemUnit(OooParams(
                machineSystem = true, pmpEntries = entries, registeredPmpRegions = selected)))
            for (i <- 0 until 16) {
                val names = Seq(s"pmpRegionLow_$i", s"pmpRegionEnd_$i", s"pmpRegionActive_$i")
                for (name <- names) {
                    val count = ("(?m)^\\s*regreset " + name + " :").r.findAllIn(fir).size
                    assert(count == (if (selected && i < entries) 1 else 0), name)
                }
            }
            assert(fir.contains("pmpCfg") && fir.contains("pmpAddr"))
        }
    }
}
