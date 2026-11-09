package platform

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import java.nio.file.{Files, Paths}
import soc.platform._
import soc.core.ooo.SideEffectFreeFetchRange

/** Deliberately separate from public board admission. Actual CPU, CDC and fabric,
  * with peripheral service ports and DDR AXI exposed, not mocked or blackboxed.
  */
object CombinedA1FabricTimingConfig {
    val profile = CommonCpuProfile.A1
    val boundary = profile.boundary
    val peripherals = CommonPeripheralConfig()
    def fabric(mode: String): CommonFabricDmaExperiment.Resolved = {
        require(Set("candidate", "baseline", "unselected", "efficiency4-candidate", "efficiency4-baseline").contains(mode))
        CommonFabricDmaExperiment.resolve(profile, peripherals, boundary,
            if (mode == "unselected") None else Some(CommonFabricDmaExperiment.ProbeAcquire))
    }
    def cpu(mode: String) = {
        val base = if (mode.startsWith("efficiency4-")) CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4.config
            else profile.fpga
        base.copy(indirectTargetEntries = 16,
            bankedIndirectStorage = mode.endsWith("candidate"),
            compactIssueImmediates = mode.endsWith("candidate"))
    }
    def memoryProfile(mode: String) =
        if (mode.startsWith("efficiency4-")) CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4.memoryProfile else None
    // Preserve the established third-fetch horizon's bounded physical RAM range.
    def safeFetchRanges(mode: String): Seq[SideEffectFreeFetchRange] =
        if (mode.startsWith("efficiency4-"))
            Seq(SideEffectFreeFetchRange(BigInt("80200000", 16), BigInt(128 * 1024))) else Seq.empty
}

class CombinedA1FabricTimingTop(mode: String) extends RawModule {
    import CombinedA1FabricTimingConfig._
    val cpuClock = IO(Input(Clock()))
    val fabricClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val bootEnable = IO(Input(Bool()))
    val ddrReady = IO(Input(Bool()))
    private val release = Module(new soc.ip.bus.CdcResetRelease)
    release.clockIn := fabricClock
    release.asyncReset := commonColdReset
    private val started = withClockAndReset(fabricClock, release.resetOut) {
        val admitted = RegInit(false.B)
        when(bootEnable && ddrReady) { admitted := true.B }
        when(admitted) { assert(ddrReady, "DDR readiness lost: common cold reset required") }
        admitted
    }
    private val startupReset = (commonColdReset.asBool || !started).asAsyncReset
    private val cpuRelease = Module(new soc.ip.bus.CdcResetRelease)
    cpuRelease.clockIn := cpuClock
    cpuRelease.asyncReset := startupReset
    val crossing = Module(new CommonCpuClockBoundary(boundary, depth = 16))
    crossing.cpuClock := cpuClock
    crossing.fabricClock := fabricClock
    crossing.commonColdReset := startupReset
    private val selection = fabric(mode)
    val sharedFabric = withClockAndReset(fabricClock, release.resetOut) {
        Module(new CommonMachineFabric(boundary = boundary, fpga = selection.fpga,
            features = peripherals.features, ramBytes = selection.fpga.ddrBytes,
            externalDdr = true, programmable = true, vivadoMemories = false,
            dmaMaintenanceCompletionFlow = selection.completionFlow,
            dmaReadAcquireOverlap = selection.readOverlap, dmaProbeAcquireOverlap = selection.probeOverlap))
    }
    val tile = withClockAndReset(cpuClock, cpuRelease.resetOut) {
        Module(new CommonA1CpuTile(config = cpu(mode), boundary = boundary,
            memoryProfile = memoryProfile(mode), sideEffectFreeFetchRanges = safeFetchRanges(mode)))
    }
    crossing.cpu <> tile.io.bus
    sharedFabric.io.tile <> crossing.fabric
    sharedFabric.io.transportCpuEmptySynchronized := crossing.cpuEmptyInFabric
    sharedFabric.io.fabricTransportEmpty := crossing.fabricTransportEmpty
    sharedFabric.io.ddrReady.get := ddrReady
    tile.io.hold := false.B
    tile.io.inspectRegister := 0.U

    // Keep every external service boundary and passive CPU output visible.
    // No fabricated responses, owners, clock sources or active test observers.
    private def leaves(data: Data, prefix: String): Seq[(String, Data)] = data match {
        case record: Record => record.elements.toSeq.flatMap { case (name, value) =>
            leaves(value, prefix + "__" + name)
        }
        case vector: Vec[_] => vector.zipWithIndex.flatMap { case (value, index) =>
            leaves(value, prefix + "_" + index)
        }.toSeq
        case leaf => Seq(prefix -> leaf)
    }
    private val internalFabric = Set("tile", "transportCpuEmptySynchronized", "fabricTransportEmpty", "ddrReady")
    private val internalCpu = Set("bus", "hold", "inspectRegister")
    private val fields = sharedFabric.io.elements.toSeq.filterNot(x => internalFabric(x._1))
        .flatMap { case (name, data) => leaves(data, "fabric__" + name) } ++
        tile.io.elements.toSeq.filterNot(x => internalCpu(x._1))
            .flatMap { case (name, data) => leaves(data, "cpu__" + name) }
    val io = IO(new CommonFabricFlatPort(fields))
    fields.foreach { case (name, leaf) => io.elements(name) <> leaf }
}

object CombinedA1FabricTimingMain extends App {
    require(args.length == 3 || (args.length == 4 && args(3) == "--emit-chirrtl-only"),
        "fresh-output-directory candidate|baseline|unselected|efficiency4-candidate|efficiency4-baseline compile-receipt [--emit-chirrtl-only]")
    val output = Paths.get(args(0)).toAbsolutePath.normalize
    require(!Files.exists(output), "fresh output required")
    val root = Paths.get(sys.props("chisel.project.root")).toAbsolutePath.normalize
    val receipt = Paths.get(args(2)).toAbsolutePath.normalize
    val binding = CommonCpuMicroarchitectureIdentity.verifyCompileReceipt(receipt, root)
    val mode = args(1)
    val selected = CombinedA1FabricTimingConfig.fabric(mode)
    val config = CombinedA1FabricTimingConfig.cpu(mode)
    val metadata = ujson.Obj(
        "schema" -> "valence-combined-a1-fabric-ooc-v1", "top" -> "CombinedA1FabricTimingTop",
        "mode" -> mode, "qualification" -> "EXPERIMENTAL_OOC_NOT_BOARD_QUALIFIED",
        "part" -> "xczu15eg-ffvb1156-2-i", "cpuClockPeriodNs" -> 10.0, "fabricClockPeriodNs" -> 4.0,
        "cpuConfig" -> CommonCpuMicroarchitectureIdentity.configuration(config),
        "effectiveCore" -> CommonCpuMicroarchitectureIdentity.value(config.coreParams),
        "memoryProfile" -> CommonCpuMicroarchitectureIdentity.value(CombinedA1FabricTimingConfig.memoryProfile(mode).map(_.name)),
        "safeFetchRanges" -> CommonCpuMicroarchitectureIdentity.value(CombinedA1FabricTimingConfig.safeFetchRanges(mode)),
        "fabricConfig" -> CommonCpuMicroarchitectureIdentity.configuration(selected.fpga),
        "completionFlow" -> selected.completionFlow, "readOverlap" -> selected.readOverlap,
        "probeOverlap" -> selected.probeOverlap, "compileBinding" -> binding,
        "rom" -> "programmable, no initial image", "externalDdr" -> true,
        "peripheralServices" -> "exposed; managed bank, PHY, MIG and board shell omitted")
    if (args.length == 4) ChiselStage.emitCHIRRTLFile(new CombinedA1FabricTimingTop(mode),
        Array("--target-dir", output.toString))
    else ChiselStage.emitSystemVerilogFile(new CombinedA1FabricTimingTop(mode),
        Array("--target-dir", output.toString), Array("--split-verilog", "--strip-debug-info",
            "--disable-all-randomization", "--lowering-options=disallowLocalVariables",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
    require(CommonCpuMicroarchitectureIdentity.verifyCompileReceipt(receipt, root) == binding,
        "compile binding changed during emission")
    Files.writeString(output.resolve("ooc-identity.json"), ujson.write(metadata, indent = 2) + "\n")
}
