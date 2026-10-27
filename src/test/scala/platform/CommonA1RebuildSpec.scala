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
            assert(config.fetchTransactionSlots == profile.fetchSlots)
            if (profile.fetchSlots == 2) assert(p.alignedFetchSinglePage)
            assert(config.cache.readMshrs == 2 && config.ddrOutstanding == 4)
            assert(p.dataReturnHandleBits == 0 && p.postedProofConfig.isEmpty)
            assert(config.cpuHz == CommonCpuProfile.A1.fpga.cpuHz)
            profile.memoryProfile.foreach(_.validate(config, CommonCpuTilePortParams()))
        }
    }

    test("tile export requires explicit valid safe RAM only for the identity horizon") {
        val old = CommonA1RebuildProfile.FullR1M3CertifiedIngress.name
        val horizon = CommonA1RebuildProfile.FullR1M3IdentityFetchHorizon.name
        val legacy = CommonA1RebuildTileArguments.parse(Array(old, "unused-output"))
        assert(legacy._1 == CommonA1RebuildProfile.FullR1M3CertifiedIngress)
        assert(legacy._2 == "unused-output" && legacy._3.isEmpty)
        intercept[IllegalArgumentException] {
            CommonA1RebuildTileArguments.parse(Array(horizon, "unused-output"))
        }
        intercept[IllegalArgumentException] {
            CommonA1RebuildTileArguments.parse(Array(old, "unused-output", "0x80200000", "131072"))
        }
        val hex = CommonA1RebuildTileArguments.parse(Array(horizon, "unused-output", "0x80200000", "0x20000"))
        val decimal = CommonA1RebuildTileArguments.parse(Array(horizon, "unused-output", "2149580800", "131072"))
        assert(hex == decimal)
        assert(hex._3.head.base == BigInt("80200000", 16) && hex._3.head.bytes == 128 * 1024)
        for ((base, bytes) <- Seq(("-1", "8"), ("2149580800", "-1"), ("2149580800", "0"),
                ("18446744073709551615", "2"))) {
            intercept[IllegalArgumentException] {
                CommonA1RebuildTileArguments.parse(Array(horizon, "unused-output", base, bytes))
            }
        }
        for (args <- Seq(Array.empty[String], Array(old), Array(old, "out", "0x80200000"),
                Array(horizon, "out", "0x80200000", "131072", "extra"))) {
            intercept[IllegalArgumentException] { CommonA1RebuildTileArguments.parse(args) }
        }
    }

    test("unknown profile and unsupported legacy factory cannot silently select another core") {
        intercept[IllegalArgumentException] { CommonA1RebuildProfile.named("300mhz-qualified") }
        intercept[IllegalArgumentException] { CommonA1RebuildProfile.Backend.config.managedBoard() }
    }
}

/** Pure argument validation; does not elaborate hardware or write output files. */
object CommonA1RebuildTileArguments {
    def parse(args: Array[String]):
        (CommonA1RebuildProfile, String, Seq[soc.core.ooo.SideEffectFreeFetchRange]) = {
        require(args.length == 2 || args.length == 4,
            "usage: CommonA1RebuildTileMain <profile-name> <output-dir> [<safe-fetch-ram-base> <safe-fetch-ram-bytes>]")
        val profile = CommonA1RebuildProfile.named(args(0))
        def number(value: String): BigInt =
            if (value.startsWith("0x")) BigInt(value.drop(2), 16) else BigInt(value)
        val safeFetchRam = if (args.length == 4) {
            require(profile.config.fetchThirdPacketLookahead,
                "explicit safe fetch RAM arguments require the identity fetch horizon profile")
            Seq(soc.core.ooo.SideEffectFreeFetchRange(number(args(2)), number(args(3))))
        } else Seq.empty[soc.core.ooo.SideEffectFreeFetchRange]
        require(!profile.config.fetchThirdPacketLookahead || safeFetchRam.nonEmpty,
            "identity fetch horizon export requires explicit actual safe RAM base and bytes")
        (profile, args(1), safeFetchRam)
    }
}

/** Explicit CPU tile export; not a replacement whole-SoC bitstream entry point. */
object CommonA1RebuildTileMain extends App {
    val (profile, outputDir, safeFetchRam) = CommonA1RebuildTileArguments.parse(args)
    ChiselStage.emitSystemVerilogFile(profile.buildTile(sideEffectFreeFetchRanges = safeFetchRam),
        Array("--target-dir", outputDir),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables", "--default-layer-specialization=enable",
            "--verification-flavor=if-else-fatal"))
}
