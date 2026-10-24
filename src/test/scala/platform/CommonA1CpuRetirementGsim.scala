package platform

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import java.nio.file.{Files, Paths}
import soc.bus.tilelink._
import soc.core.ooo._
import soc.platform._

/** Bounded actual-tile retirement fixture. The external host serves raw instruction
  * bytes through physical TileLink, never decoded instructions. VM, FPU, PMP,
  * ROB/PRF, real L1 geometry and the selected LSU/DTLB remain intact. Bare M-mode
  * integer guests do not qualify VM/FPU/data-memory functionality or board timing.
  */
object CommonA1CpuRetirementFixture {
    val profiles: Map[String, (Int, Boolean)] = Map(
        "legacy" -> (1, false), "single-page" -> (1, true), "dual-slot" -> (2, true))
    def config(profile: String, base: String): FpgaNextConfig = {
        require(profiles.contains(profile), "profile must be legacy|single-page|dual-slot")
        val (slots, aligned) = profiles(profile)
        CommonA1RebuildProfile.named(base).config.copy(
            fetchTransactionSlots = slots, alignedFetchSinglePage = aligned)
    }
    def writeFields(target: java.nio.file.Path, value: Product): Unit = {
        def escape(text: String): String = text.replace("\\", "\\\\").replace("\"", "\\\"")
            .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        val fields = value.productElementNames.zip(value.productIterator).map { case (key, entry) =>
            s"\"${escape(key)}\":\"${escape(entry.toString)}\""
        }.mkString(",\n")
        Files.writeString(target, s"{\n$fields\n}\n")
    }
}

class CommonA1CpuRetirementGsim(profile: String, base: String) extends Module {
    private val config = CommonA1CpuRetirementFixture.config(profile, base)
    private val p = config.coreParams
    private val boundary = CommonCpuTilePortParams()
    require(p.renameWidth == 2 && p.issueWidth == 2 && p.commitWidth == 2)
    require(p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64)
    require(p.machineSystem && p.fpEnabled && p.pmpEntries == 16 && p.virtualMemoryLevels == 3)
    require(config.instructionCacheLines == 512 && config.dataCacheLines == 512 && config.cacheWays == 2)
    require(config.ramBase == BigInt("80200000", 16) && CommonPlatformAbi.romBytes == 128 * 1024)
    val io = IO(new Bundle {
        val hold = Input(Bool())
        val inspectRegister = Input(UInt(5.W))
        val committedValue = Output(UInt(64.W))
        val commit0 = Output(Valid(new CommitRecord(p)))
        val commit1 = Output(Valid(new CommitRecord(p)))
        val trap = Output(Valid(new HeadException(p)))
        val instructionA = Decoupled(new TLBundleA(boundary.instruction))
        val instructionD = Flipped(Decoupled(new TLBundleD(boundary.instruction)))
        val scalar0 = new CommonTileScalarPort(boundary)
        val scalar1 = new CommonTileScalarPort(boundary)
        val acceptedInstructions = Output(UInt(2.W))
        val virtualFetchFire = Output(Bool())
        val physicalFetchFire = Output(Bool())
        val fetchIdle = Output(Bool())
        val privateIdle = Output(Bool())
        val ownersIdle = Output(Bool())
        val memoryBusy = Output(Bool())
        val robOccupancy = Output(UInt(p.countBits.W))
        val unexpectedCoherent = Output(Bool())
    })
    val tile = Module(new CommonA1CpuTile(config, boundary,
        CommonA1RebuildProfile.named(base).memoryProfile))
    tile.io.hold := io.hold
    tile.io.inspectRegister := io.inspectRegister
    io.committedValue := tile.io.committedValue
    io.commit0 := tile.io.commit(0)
    io.commit1 := tile.io.commit(1)
    io.trap := tile.io.trap
    io.memoryBusy := tile.io.memoryBusy
    io.instructionA <> tile.io.bus.instructionFetch.a
    tile.io.bus.instructionFetch.d <> io.instructionD
    TLBundle.tieoffSlaveCoherence(tile.io.bus.instructionFetch)
    assert(!tile.io.bus.instructionFetch.c.valid && !tile.io.bus.instructionFetch.e.valid,
        "instruction-only fixture received unexpected coherent I traffic")
    io.scalar0 <> tile.io.bus.scalar(0)
    io.scalar1 <> tile.io.bus.scalar(1)
    for (lane <- 0 until 2) {
        val port = tile.io.bus.coherent(lane)
        port.a.ready := true.B
        port.b.valid := false.B
        port.b.bits := 0.U.asTypeOf(port.b.bits)
        port.c.ready := true.B
        port.d.valid := false.B
        port.d.bits := 0.U.asTypeOf(port.d.bits)
        port.e.ready := true.B
        tile.io.bus.lineGrant(lane).valid := false.B
        tile.io.bus.lineGrant(lane).bits := 0.U.asTypeOf(tile.io.bus.lineGrant(lane).bits)
        assert(!port.a.valid && !port.c.valid && !port.e.valid,
            "instruction-only fixture cannot service data/coherent traffic")
        when(tile.io.bus.scalar(lane).request.valid) {
            assert(tile.io.bus.scalar(lane).request.bits.clearReservation && (lane == 1).B,
                "instruction-only fixture received a scalar memory operation")
        }
    }
    io.unexpectedCoherent := tile.io.bus.coherent.map(port =>
        port.a.valid || port.c.valid || port.e.valid).reduce(_ || _)
    tile.io.bus.msi.request.valid := false.B
    tile.io.bus.msi.request.bits := 0.U.asTypeOf(tile.io.bus.msi.request.bits)
    tile.io.bus.msi.response.ready := true.B
    tile.io.bus.timerInterrupt := false.B
    tile.io.bus.softwareInterrupt := false.B
    tile.io.bus.timeSnapshot := 0.U
    tile.io.bus.maintenance.valid := false.B
    tile.io.bus.maintenance.bits := 0.U.asTypeOf(tile.io.bus.maintenance.bits)
    tile.io.bus.maintenanceStatus.ready := false.B
    tile.io.bus.fabricDrainedEpoch.valid := false.B
    tile.io.bus.fabricDrainedEpoch.bits := 0.U
    assert(!tile.io.bus.maintenanceStatus.valid, "integer guests must not request maintenance")
    // All taps are observations; none changes request, response or acceptance.
    io.acceptedInstructions := PopCount(BoringUtils.bore(tile.core.io.accepted))
    io.virtualFetchFire := BoringUtils.bore(tile.frontend.io.memory.request.valid) &&
        BoringUtils.bore(tile.frontend.io.memory.request.ready)
    io.physicalFetchFire := BoringUtils.bore(tile.fetchCache.io.fetch.request.valid) &&
        BoringUtils.bore(tile.fetchCache.io.fetch.request.ready)
    io.fetchIdle := BoringUtils.bore(tile.fetchIdle)
    io.privateIdle := BoringUtils.bore(tile.privateIdle) && BoringUtils.bore(tile.cache.io.quiescent)
    io.ownersIdle := BoringUtils.bore(tile.core.core.core.backend.io.ownersIdle)
    io.robOccupancy := BoringUtils.bore(tile.core.io.robOccupancy)
}

object CommonA1CpuRetirementGsimMain extends App {
    require(args.length >= 2 && args.length <= 3, "output-directory profile [fixed-base-profile]")
    val base = args.lift(2).getOrElse("combined-branch")
    val config = CommonA1CpuRetirementFixture.config(args(1), base)
    val target = Paths.get(args(0))
    Files.createDirectories(target)
    CommonA1CpuRetirementFixture.writeFields(target.resolve("effective-config.json"), config)
    CommonA1CpuRetirementFixture.writeFields(target.resolve("effective-parameters.json"), config.coreParams)
    Files.writeString(target.resolve("effective-geometry.json"),
        s"""{"instructionCacheBytes":${config.instructionCacheLines * 64},
           |"dataCacheBytes":${config.dataCacheLines * 64},"cacheWays":${config.cacheWays},
           |"isaProfile":"${config.isaProfile}","robEntries":${config.coreParams.robEntries},
           |"physicalRegs":${config.coreParams.physicalRegs},"lsuEntries":${config.coreParams.memoryEntries},
           |"dataTranslationEntries":${config.dataTranslationEntries},"pmpEntries":${config.coreParams.pmpEntries},
           |"virtualMemoryLevels":${config.coreParams.virtualMemoryLevels},"fpEnabled":${config.coreParams.fpEnabled},
           |"romBytes":${CommonPlatformAbi.romBytes},"ramBase":"${config.ramBase}","ramBytes":"${config.ddrBytes}"}
           |""".stripMargin)
    Files.writeString(target.resolve("fixture-scope.txt"),
        s"profile=${args(1)} base=$base; actual CommonA1CpuTile; bare M-mode; raw instruction TL; " +
        "VM/PMP/FPU retained, not active qualification; no board/CDC/peripherals/timing claim\n")
    ChiselStage.emitCHIRRTLFile(new CommonA1CpuRetirementGsim(args(1), base), Array("--target-dir", args(0)))
}
