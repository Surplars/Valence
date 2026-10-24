package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.platform._

class CommonA1RebuildSpec extends AnyFunSuite {
    test("A1 rebuild baseline is the actual public A1 configuration") {
        assert(CommonA1RebuildProfile.Baseline.config == CommonCpuProfile.A1.fpga)
        assert(CommonA1RebuildProfile.Baseline.memoryProfile.isEmpty)
        assert(CommonCpuProfile.A1.fpga.coreParams.completionTopology == "legacy")
    }

    test("explicit controls separate completion, memory and branch changes") {
        for (profile <- CommonA1RebuildProfile.all) {
            val config = profile.config
            val p = config.coreParams
            assert(p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2)
            assert(p.robEntries == 16 && p.physicalRegs == 48 && p.storeBufferEntries == 2)
            assert(p.memoryEntries == (if (profile.parallelMemory) 4 else 2))
            assert(p.completionTopology == (if (profile.dualCompletion) "dual-owner" else "legacy"))
            assert(p.branchResolutionTopology ==
                (if (profile.independentBranch) "execution-mailbox" else "writeback-coupled"))
            assert(config.cache.readMshrs == 2 && config.ddrOutstanding == 4)
            assert(p.dataReturnHandleBits == 0 && p.postedProofConfig.isEmpty)
            assert(config.cpuHz == CommonCpuProfile.A1.fpga.cpuHz)
            profile.memoryProfile.foreach(_.validate(config, CommonCpuTilePortParams()))
        }
    }

    test("unknown profile and unsupported legacy factory cannot silently select another core") {
        intercept[IllegalArgumentException] { CommonA1RebuildProfile.named("300mhz-qualified") }
        intercept[IllegalArgumentException] { CommonA1RebuildProfile.Backend.config.managedBoard() }
    }
}

/** Explicit CPU tile export; not a replacement whole-SoC bitstream entry point. */
object CommonA1RebuildTileMain extends App {
    require(args.length == 2, "usage: CommonA1RebuildTileMain <baseline|backend|memory|combined|backend-branch|combined-branch> <output-dir>")
    val profile = CommonA1RebuildProfile.named(args(0))
    ChiselStage.emitSystemVerilogFile(profile.buildTile(), Array("--target-dir", args(1)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables", "--default-layer-specialization=enable",
            "--verification-flavor=if-else-fatal"))
}
