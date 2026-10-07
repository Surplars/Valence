package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

/** Exact opt-in board timing profile, with passive ownership/credit witnesses only.
  * Recovery is produced by a real dependent branch; the selected pipeline forbids external recovery injection.
  */
class MemoryCapacityBackendGsim extends Module {
    val p = BoardSocConfig.timingParams(BoardSocConfig.memoryCapacityProfile)
    require(p == BoardSocConfig.timingParams("staged-fetch-turnover").copy(memoryEntries = 4))
    require(p.renameWidth == 2 && p.commitWidth == 2 && p.completionWidth == 2)
    require(p.robEntries == 16 && p.physicalRegs == 48 && p.branchPredictorEntries == 32)

    val io = IO(new Bundle {
        val allocate0 = Input(Valid(new IntegerRequest))
        val allocate1 = Input(Valid(new IntegerRequest))
        val renamed0 = Output(Valid(new RenamedInstruction(p)))
        val renamed1 = Output(Valid(new RenamedInstruction(p)))
        val commit0 = Output(Valid(new CommitRecord(p)))
        val commit1 = Output(Valid(new CommitRecord(p)))
        val issued0 = Output(Valid(new BackendCompletion(p)))
        val issued1 = Output(Valid(new BackendCompletion(p)))
        val commitEnable = Input(Bool())
        val recovering = Output(Bool())
        val occupancy = Output(UInt(p.countBits.W))
        val headException = Output(Valid(new HeadException(p)))
        val inspectRegister = Input(UInt(5.W))
        val committedValue = Output(UInt(64.W))
        val redirect = Output(Valid(new FrontendRedirect(p)))
        val memory = new DataPort
        val memoryBusy = Output(Bool())
        val issueCount = Output(UInt(log2Ceil(p.issueWidth + 1).W))
        val memoryDiscarded = Output(Bool())
        val memoryForwarded = Output(Bool())
        val lsuLiveMask = Output(UInt(4.W))
        val lsuDiscardMask = Output(UInt(4.W))
        val lsuOwner0 = Output(new RobToken(p))
        val lsuOwner1 = Output(new RobToken(p))
        val lsuOwner2 = Output(new RobToken(p))
        val lsuOwner3 = Output(new RobToken(p))
        val lsuOwnerCredits = Output(UInt(3.W))
        val queuedRequests = Output(UInt(3.W))
        val storeOwnerCredits = Output(UInt(3.W))
        val pendingReads = Output(UInt(3.W))
        val bufferedStores = Output(UInt(2.W))
    })
    val backend = Module(new IntegerBackend(p))
    backend.io.allocate(0) := io.allocate0
    backend.io.allocate(1) := io.allocate1
    backend.io.rawDestinations.foreach { destinations =>
        destinations(0) := io.allocate0.bits.rename.rd
        destinations(1) := io.allocate1.bits.rename.rd
    }
    backend.io.rawRequests.foreach { requests =>
        requests(0) := io.allocate0.bits.rename
        requests(1) := io.allocate1.bits.rename
    }
    backend.io.fetchFaultMask.foreach(_ := 0.U)
    backend.io.recover := 0.U.asTypeOf(Valid(new RecoveryRequest(p)))
    backend.io.commitEnable := io.commitEnable
    backend.io.inspectRegister := io.inspectRegister
    io.renamed0 := backend.io.renamed(0)
    io.renamed1 := backend.io.renamed(1)
    io.commit0 := backend.io.commit(0)
    io.commit1 := backend.io.commit(1)
    io.issued0 := backend.io.issued(0)
    io.issued1 := backend.io.issued(1)
    io.recovering := backend.io.recovering
    io.occupancy := backend.io.occupancy
    io.headException := backend.io.headException
    io.committedValue := backend.io.committedValue
    io.redirect := backend.io.redirect
    io.memory <> backend.io.memory
    io.memoryBusy := backend.io.memoryBusy
    io.issueCount := backend.io.issueCount
    io.memoryDiscarded := backend.io.memoryDiscarded
    io.memoryForwarded := backend.io.memoryForwarded

    // Static scalar taps avoid dynamic output aliases in the pinned GSIM graph pass.
    // None of these signals participates in stimulus, ownership selection, or DUT control.
    def tap[T <: Data](signal: T): T = BoringUtils.bore(signal)
    io.lsuLiveMask := Cat((0 until 4).reverse.map(i => tap(backend.lsu.io.live(i))))
    io.lsuDiscardMask := Cat((0 until 4).reverse.map(i => tap(backend.lsu.slots(i).io.discarded)))
    for ((owner, i) <- Seq(io.lsuOwner0, io.lsuOwner1, io.lsuOwner2, io.lsuOwner3).zipWithIndex) {
        owner.index := tap(backend.lsu.io.owner(i).index)
        owner.tag := tap(backend.lsu.io.owner(i).tag)
    }
    io.lsuOwnerCredits := tap(backend.lsu.owners.io.count)
    io.queuedRequests := tap(backend.observationRequests.get.io.count)
    io.storeOwnerCredits := tap(backend.observationStores.get.owners.io.count)
    io.pendingReads := tap(backend.observationStores.get.reads)
    io.bufferedStores := tap(backend.observationStores.get.count)
}

object MemoryCapacityBackendGsimMain extends App {
    val target = args.headOption.getOrElse("build/gsim/memory-capacity-backend")
    ChiselStage.emitCHIRRTLFile(new MemoryCapacityBackendGsim, Array("--target-dir", target))
}
