package platform

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util.experimental.BoringUtils
import soc.bus.tilelink.TLBundle
import soc.core.ooo._
import soc.platform._
import java.nio.file.{Files, Paths}

/** Exact final Selected-derived parameters, including its Some(true) load
  * forwarding override. These emitters do not change any production default.
  */
object CommonA1MemoryParallelFixture {
    def config: FpgaNextConfig = CommonA1RebuildProfile.Memory.config
    def selected(name: String): FpgaNextConfig = {
        require(Set("memory", "combined").contains(name), "memory fixture requires memory|combined")
        CommonA1RebuildProfile.named(name).config
    }
}

object CommonA1MemoryTileMain extends App {
    require((args.length == 2 || args.length == 3) && Set("static", "park").contains(args(1)),
        "output-directory static|park [memory|combined]")
    val runtime = args(1) == "park"
    val boundary = CommonCpuTilePortParams(runtimeMaintenance = runtime,
        runtimeCancellation = runtime, runtimeInterruptHold = runtime)
    ChiselStage.emitCHIRRTLFile(new CommonA1CpuTile(
        CommonA1MemoryParallelFixture.selected(args.lift(2).getOrElse("memory")), boundary,
        Some(CommonA1MemoryProfile.ExperimentalMemoryParallel)), Array("--target-dir", args(0)))
    val rtl = Files.readString(Paths.get(args(0), "CommonA1CpuTile.fir"))
    require(rtl.contains("module VirtualRamLoadPreparation"), "actual A1 tile omitted virtual load preparation")
    require(rtl.contains("inst slots_3 of LoadStoreUnit"), "actual A1 tile omitted its fourth LSU owner")
    require(rtl.linesIterator.exists(line => line.contains("regreset tlb :") && line.contains("[16]")),
        "actual A1 tile omitted its 16-entry DTLB")
    require(rtl.contains("module DataResponseBuffer") && rtl.contains("canonicalStoreCertificate") &&
        rtl.contains("relaxStoreOwner"), "actual A1 tile omitted canonical/checked return ownership")
    require(rtl.contains("module CommonA1RuntimePark") == runtime, "actual A1 park profile changed")
    println(s"A1_MEMORY_TILE_COMPOSITION_PASS runtime=$runtime lsu=4 dtlb=16 ordered_return=1")
}

/** Actual LSU ownership parameters; external MemoryOperation permission is a
  * fixture premise, not a substitute for the backend/MMU qualification below.
  */
object CommonA1MemoryLsuMain extends App {
    require(args.length == 1 || args.length == 2, "output-directory [2|4]")
    val entries = args.lift(1).map(_.toInt).getOrElse(4)
    require(Set(2, 4).contains(entries), "bounded LSU completion-credit check requires 2 or 4 slots")
    // Four slots use the exact combined candidate. The two-slot control changes
    // only capacity, retaining the same early dual-completion credit contract.
    val p = CommonA1RebuildProfile.Combined.config.coreParams.copy(memoryEntries = entries)
    ChiselStage.emitCHIRRTLFile(new ooo.CanonicalStoreLsuGsim(entries, canonicalHandoff = true,
        actualParams = Some(p)), Array("--target-dir", args(0)))
}

/** Actual decoded backend, registered request FIFO/SB, checked translator and
  * DTLB16. Independent software page tables and architectural bytes belong to
  * canonical_virtual_store_backend.cpp, not to the observation taps.
  */
object CommonA1MemoryBackendMain extends App {
    require(args.length == 1 || args.length == 2, "output-directory [memory|combined]")
    ChiselStage.emitCHIRRTLFile(new ooo.CanonicalVirtualStoreBackendGsim(true, 4,
        Some(CommonA1MemoryParallelFixture.selected(args.lift(1).getOrElse("memory")))),
        Array("--target-dir", args(0)))
}

/** Actual A1 L1D geometry/policy and two response credits. The short manager
  * deliberately exercises source-reversed legacy D grants while the production
  * whole-line input is idle; whole-line CDC is covered by the real tile graph.
  */
class CommonA1MemoryCacheGsim extends Module {
    private val c = CommonA1MemoryParallelFixture.config
    private val boundary = CommonCpuTilePortParams()
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val downstream = new DataPort
        val tl = new TLBundle(boundary.coherent)
        val flushRequest = Input(Bool())
        val flushDone = Output(Bool())
        val hit = Output(Bool())
        val miss = Output(Bool())
        val mshrOccupancy = Output(UInt(3.W))
    })
    val cache = Module(new NonBlockingCoherentLineCache(c.ramBase, c.ddrBytes, c.dataCacheLines,
        boundary.coherent, c.cacheWays, c.cache, c.tags))
    io.upstream <> cache.io.upstream
    io.downstream <> cache.io.downstream
    io.tl <> cache.io.tl
    cache.io.lineGrant.get.valid := false.B
    cache.io.lineGrant.get.bits := 0.U.asTypeOf(cache.io.lineGrant.get.bits)
    cache.io.flushRequest := io.flushRequest
    io.flushDone := cache.io.flushDone
    io.hit := cache.io.hit
    io.miss := cache.io.miss
    io.mshrOccupancy := BoringUtils.bore(cache.mshrOccupancy)
}

object CommonA1MemoryCacheMain extends App {
    ChiselStage.emitCHIRRTLFile(new CommonA1MemoryCacheGsim, Array("--target-dir", args(0)))
}
