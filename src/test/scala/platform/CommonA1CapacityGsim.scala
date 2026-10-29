package platform

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import java.nio.file.{Files, Paths}
import soc.bus.tilelink._
import soc.platform._
import soc.core.ooo._

/** Generic production CPU tile; only test IO and passive architectural/drain observations.
  * No experimental profile or feature is enabled to satisfy a historical host.
  */
class CommonA1CapacityGsim(spec: CommonA1CpuSpec) extends Module {
    private val profile = CommonCpuProfile.A1
    private val boundary = profile.boundary
    private val config = CommonA1CpuSpec.resolve(profile, None, Some(spec), boundary)
    private val p = config.coreParams
    require(p.renameWidth == 2 && p.issueWidth == 2 && p.commitWidth == 2)
    require(p.tagBits == 64 && p.robEntries == spec.robEntries &&
        p.physicalRegs == spec.physicalRegs && p.memoryEntries == spec.lsuOwners)
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
        val fetchIdle = Output(Bool())
        val privateIdle = Output(Bool())
        val ownersIdle = Output(Bool())
        val memoryBusy = Output(Bool())
        val robOccupancy = Output(UInt(p.countBits.W))
        val unexpectedCoherent = Output(Bool())
        val dataA = Decoupled(new TLBundleA(boundary.coherent))
        val dataC = Decoupled(new TLBundleC(boundary.coherent))
        val dataE = Decoupled(new TLBundleE(boundary.coherent))
        val dataGrant = Flipped(Decoupled(new Bundle {
            val source = UInt(boundary.coherent.sourceBits.W)
            val sink = UInt(boundary.coherent.sinkBits.W)
            val cap = UInt(2.W)
            val denied = Bool(); val corrupt = Bool()
            val data0 = UInt(64.W)
            val data1 = UInt(64.W)
            val data2 = UInt(64.W)
            val data3 = UInt(64.W)
            val data4 = UInt(64.W)
            val data5 = UInt(64.W)
            val data6 = UInt(64.W)
            val data7 = UInt(64.W)
        }))
        // Physical request acceptance before the private L1D, not external DDR traffic.
        val physical = Output(Valid(new DataRequest(p.dataReturnHandleBits)))
        val physicalResponse = Output(Bool())
        val dataD = Flipped(Decoupled(new TLBundleD(boundary.coherent)))
    })
    val tile = Module(new CommonA1CpuTile(config, boundary, None))
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
    // Lane zero is the deliberately inactive coherent I-client. The actual
    // L1D on lane one is connected to a bounded legal external Home manager.
    val inactive = tile.io.bus.coherent(0)
    inactive.a.ready := false.B; inactive.b.valid := false.B
    inactive.b.bits := 0.U.asTypeOf(inactive.b.bits); inactive.c.ready := false.B
    inactive.d.valid := false.B; inactive.d.bits := 0.U.asTypeOf(inactive.d.bits)
    inactive.e.ready := false.B
    tile.io.bus.lineGrant(0).valid := false.B
    tile.io.bus.lineGrant(0).bits := 0.U.asTypeOf(tile.io.bus.lineGrant(0).bits)
    assert(!inactive.a.valid && !inactive.c.valid && !inactive.e.valid,
        "inactive coherent I lane must not issue traffic")
    io.dataA <> tile.io.bus.coherent(1).a
    io.dataC <> tile.io.bus.coherent(1).c
    io.dataE <> tile.io.bus.coherent(1).e
    tile.io.bus.coherent(1).b.valid := false.B
    tile.io.bus.coherent(1).b.bits := 0.U.asTypeOf(tile.io.bus.coherent(1).b.bits)
    tile.io.bus.coherent(1).d <> io.dataD
    val grant = tile.io.bus.lineGrant(1)
    grant.valid := io.dataGrant.valid; io.dataGrant.ready := grant.ready
    grant.bits.source := io.dataGrant.bits.source; grant.bits.sink := io.dataGrant.bits.sink
    grant.bits.cap := io.dataGrant.bits.cap; grant.bits.denied := io.dataGrant.bits.denied
    grant.bits.corrupt := io.dataGrant.bits.corrupt
    grant.bits.data := Cat(io.dataGrant.bits.data7, io.dataGrant.bits.data6, io.dataGrant.bits.data5, io.dataGrant.bits.data4, io.dataGrant.bits.data3, io.dataGrant.bits.data2, io.dataGrant.bits.data1, io.dataGrant.bits.data0)
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
    assert(!tile.io.bus.maintenanceStatus.valid, "bounded VM guests exclude FENCE.I/global fabric maintenance")
    // The tile has no public drain outputs. These four passive observations do
    // not feed request/response/control; cache quiescence is part of private drain.
    io.fetchIdle := BoringUtils.bore(tile.fetchIdle)
    io.privateIdle := BoringUtils.bore(tile.privateIdle) && BoringUtils.bore(tile.cache.io.quiescent)
    io.ownersIdle := BoringUtils.bore(tile.core.core.core.backend.io.ownersIdle)
    io.robOccupancy := BoringUtils.bore(tile.core.io.robOccupancy)
    // dataTranslation=true in CommonA1CpuTile, independent of optional experiments.
    // A denied warm-cache access must not disappear behind an external-bus check.
    val adapter = tile.core.observationTranslation.get
    io.physical.valid := BoringUtils.bore(adapter.io.physical.request.valid) &&
        BoringUtils.bore(adapter.io.physical.request.ready)
    io.physical.bits := BoringUtils.bore(adapter.io.physical.request.bits)
    io.physicalResponse := BoringUtils.bore(adapter.io.physical.response.valid) &&
        BoringUtils.bore(adapter.io.physical.response.ready)
}

object CommonA1CapacityGsimMain extends App {
    require(args.length == 3, "output-directory rob-entries physical-registers")
    val spec = CommonA1CpuSpec(4, args(1).toInt, args(2).toInt)
    require(Set((16, 48), (16, 64), (32, 64)).contains((spec.robEntries, spec.physicalRegs)),
        "bounded capacity qualification selects 16/48, 16/64 or 32/64 with LSU4")
    val profile = CommonCpuProfile.A1
    val config = CommonA1CpuSpec.resolve(profile, None, Some(spec), profile.boundary)
    val out = Paths.get(args(0)); Files.createDirectories(out)
    val identity = CommonCpuMicroarchitectureIdentity.build(profile, None, profile.boundary, cpuSpec = Some(spec))
    Files.writeString(out.resolve("cpu-identity.json"), ujson.write(identity, indent = 2) + "\n")
    CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-config.json"), config)
    CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-parameters.json"), config.coreParams)
    Files.writeString(out.resolve("scope.txt"),
        "Actual generic CommonA1CpuTile; bounded execution only, no full SoC/OS/FP-complete/PPA qualification.\n")
    ChiselStage.emitCHIRRTLFile(new CommonA1CapacityGsim(spec), Array("--target-dir", args(0)))
}
