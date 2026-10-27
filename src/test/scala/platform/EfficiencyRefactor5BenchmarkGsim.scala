package soc.core.ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import java.nio.file.{Files, Paths}
import soc.bus.tilelink._
import soc.platform._

/** Benchmark-only extension of the frozen passive VM fixture.
  * Exposes the real coherent D channel so dirty evictions receive ReleaseAck.
  * Cache capacities and the qualified third-fetch range are unchanged;
  * the explicit candidate retains all earlier batches and adds only checked load payload nomination.
  * The host is a single-hart RAM home, never a probe generator.
  */
class EfficiencyRefactor5BenchmarkGsim
    extends CommonA1VmPipelineGsim(
      "full-r1-m3-efficiency-refactor-5",
      Seq(SideEffectFreeFetchRange(BigInt("80200000", 16), BigInt(128 * 1024)))
    ) {
    private val benchmarkBoundary = CommonCpuTilePortParams()
    val benchmark = IO(new Bundle {
        val dataD = Flipped(Decoupled(new TLBundleD(benchmarkBoundary.coherent)))
    })
    // The inherited fixture ties D low. This later connection deliberately
    // replaces that test-only tieoff, not a production datapath connection.
    tile.io.bus.coherent(1).d <> benchmark.dataD
}

object EfficiencyRefactor5BenchmarkGsimMain extends App {
    require(args.length == 1, "output-directory")
    val out = Paths.get(args(0))
    Files.createDirectories(out)
    val selected = CommonA1RebuildProfile.named("full-r1-m3-efficiency-refactor-5")
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-config.json"), selected.config)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(
        out.resolve("effective-parameters.json"), selected.config.coreParams)
    Files.writeString(out.resolve("scope.txt"),
      "Experimental fifth efficiency profile; passive VM observations plus real coherent D input. " +
        "Single-hart RAM benchmark, no external probes, FENCE.I/global maintenance, atomics, or VM. " +
        "Third-fetch safe range remains [0x80200000,0x80220000). No PPA qualification.\n")
    ChiselStage.emitCHIRRTLFile(new EfficiencyRefactor5BenchmarkGsim, Array("--target-dir", args(0)))
}
