package ooo

import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

class BackendCapacityConfigSpec extends AnyFunSuite {
    test("omitted overrides preserve every existing base and board timing variant") {
        val empty = BackendCapacityConfig()
        assert(empty.configure(OooParams()) == OooParams())
        assert(empty.configure(OooParams()).robEntries == 32)
        for (profile <- BoardSocConfig.timingProfiles; width <- Seq(2, 4)
            if profile != BoardSocConfig.memoryCapacityProfile || width == 2) {
            val p = BoardSocConfig.timingParams(profile, width)
            assert(empty.configure(p) == p)
            assert(p.robEntries == 16 && p.physicalRegs == 48)
        }
        for (selector <- Seq("--reference", "--candidate", "--selected")) {
            val c = FpgaNextConfig.fromOptions(Set(selector), defaultSelected = true)
            assert(c.robEntries.isEmpty && c.physicalRegs.isEmpty)
            assert(c.coreParams.robEntries == 16 && c.coreParams.physicalRegs == 48)
        }
    }

    test("explicit capacities alter only ROB and PRF dimensions and preserve storage") {
        for (selector <- Seq("--reference", "--candidate", "--selected");
            rob <- Seq(16, 32, 64); regs <- Seq(48, 64)) {
            val options = Set(selector, "--lsu-entries=4")
            val base = FpgaNextConfig.fromOptions(options, defaultSelected = true)
            val c = FpgaNextConfig.fromOptions(options ++ Set(s"--rob-entries=$rob", s"--physical-regs=$regs"), true)
            assert(c.coreParams == base.coreParams.copy(robEntries = rob, physicalRegs = regs))
            assert(c.coreParams.renameWidth == 2 && c.coreParams.commitWidth == 2 && c.coreParams.completionWidth == 2)
            assert(c.coreParams.memoryEntries == 4 && c.coreParams.tagBits == 64)
            assert(c.coreParams.robBits == Integer.numberOfTrailingZeros(rob))
            assert(c.cache == base.cache && c.ddr == base.ddr && c.storage == base.storage)
            assert(c.tags == base.tags && c.network == base.network && c.timingProfile == base.timingProfile)
            assert(c.name == base.name + s"-rob$rob-prf$regs")
        }
    }

    test("single dimension overrides do not infer a change to another capacity") {
        val base = FpgaNextConfig.Selected
        val prf = FpgaNextConfig.fromOptions(Set("--selected", "--physical-regs=64"), true)
        val rob = FpgaNextConfig.fromOptions(Set("--selected", "--rob-entries=64"), true)
        assert(prf.coreParams == base.coreParams.copy(physicalRegs = 64))
        assert(rob.coreParams == base.coreParams.copy(robEntries = 64))
        assert(BackendCapacityConfig(physicalRegs = Some(48)).configure(OooParams()).robEntries == 32)
    }

    test("unsupported geometry, conflicting options and width expansion fail closed") {
        for (n <- Seq(0, 8, 24, 128)) {
            intercept[IllegalArgumentException] { FpgaNextConfig(robEntries = Some(n)) }
        }
        for (n <- Seq(0, 32, 47, 96, 256)) {
            intercept[IllegalArgumentException] { FpgaNextConfig(physicalRegs = Some(n)) }
        }
        for (options <- Seq(Set("--rob-entries=16", "--rob-entries=64"),
            Set("--physical-regs=48", "--physical-regs=64"), Set("--lsu-entries=8"))) {
            intercept[IllegalArgumentException] { FpgaNextConfig.fromOptions(options, true) }
        }
        intercept[IllegalArgumentException] {
            BackendCapacityConfig(robEntries = Some(64)).configure(OooParams(renameWidth = 4))
        }
    }
}
