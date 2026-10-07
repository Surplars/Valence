package ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Scalar test ports for the pinned GSIM accessor API. */
class LoadIssueForwardingGsim(p: OooParams) extends Module {
    require(p.renameWidth == 2 && p.commitWidth == 2 && p.completionWidth == 2)

    val io = IO(new Bundle {
        val allocate0        = Input(Valid(new IntegerRequest))
        val allocate1        = Input(Valid(new IntegerRequest))
        val renamed0         = Output(Valid(new RenamedInstruction(p)))
        val renamed1         = Output(Valid(new RenamedInstruction(p)))
        val commit0          = Output(Valid(new CommitRecord(p)))
        val commit1          = Output(Valid(new CommitRecord(p)))
        val issued0          = Output(Valid(new BackendCompletion(p)))
        val issued1          = Output(Valid(new BackendCompletion(p)))
        val commitEnable     = Input(Bool())
        val recover          = Input(Valid(new RecoveryRequest(p)))
        val recoveryAccepted = Output(Bool())
        val recovering       = Output(Bool())
        val occupancy        = Output(UInt(p.countBits.W))
        val headException    = Output(Valid(new HeadException(p)))
        val inspectRegister  = Input(UInt(5.W))
        val committedValue   = Output(UInt(64.W))
        val redirect         = Output(Valid(new FrontendRedirect(p)))
        val memory           = new DataPort
        val memoryBusy       = Output(Bool())
        val issueCount       = Output(UInt(log2Ceil(p.issueWidth + 1).W))
        val memoryDiscarded  = Output(Bool())
        val memoryForwarded  = Output(Bool())
        val rawLoadComplete = Output(Bool())
        val heldLoadComplete = Output(Bool())
        val slotReplacement = Output(Bool())
        val mixedForwarding = Output(Bool())
        val forwarded0 = Output(UInt(2.W))
        val forwarded1 = Output(UInt(2.W))
    })
    val backend = Module(new IntegerBackend(p))
    val completion = BoringUtils.bore(backend.lsu.io.complete.valid)
    io.rawLoadComplete := completion
    io.heldLoadComplete := completion && BoringUtils.bore(backend.executionStages(0).io.deq.valid) &&
        !BoringUtils.bore(backend.executionStages(0).io.deq.ready)
    io.slotReplacement := backend.lsu.slots.map { slot =>
        BoringUtils.bore(slot.io.start.valid) && BoringUtils.bore(slot.io.start.ready) &&
            BoringUtils.bore(slot.io.complete.valid) && BoringUtils.bore(slot.io.complete.ready)
    }.reduce(_ || _)
    val sources1 = VecInit((0 until p.robEntries).map(i => BoringUtils.bore(backend.queue(i).renamed.source1)))
    val sources2 = VecInit((0 until p.robEntries).map(i => BoringUtils.bore(backend.queue(i).renamed.source2)))
    val usePc = VecInit((0 until p.robEntries).map(i => BoringUtils.bore(backend.queue(i).request.usePc)))
    val useImmediate = VecInit((0 until p.robEntries).map(i => BoringUtils.bore(backend.queue(i).request.useImmediate)))
    val dispatched = BoringUtils.bore(backend.dispatched)
    val wakes = BoringUtils.bore(backend.executionWake)
    io.mixedForwarding := (0 until p.completionWidth).map { lane =>
        val forwarded = backend.io.loadIssueForwarded.get(lane)
        val index = Mux(dispatched(lane).valid, dispatched(lane).bits, 0.U)
        val source1 = sources1(index)
        val source2 = sources2(index)
        wakes.map(wake => wake.valid && ((forwarded(0) && !useImmediate(index) && wake.bits === source2) ||
            (forwarded(1) && !usePc(index) && wake.bits === source1))).reduce(_ || _)
    }.reduce(_ || _)
    io.forwarded0 := backend.io.loadIssueForwarded.get(0)
    io.forwarded1 := backend.io.loadIssueForwarded.get(1)
    backend.io.rawDestinations.foreach { rd =>
        rd(0) := io.allocate0.bits.rename.rd
        rd(1) := io.allocate1.bits.rename.rd
    }
    io.memory <> backend.io.memory
    io.memoryBusy              := backend.io.memoryBusy
    io.issueCount              := backend.io.issueCount
    io.memoryDiscarded         := backend.io.memoryDiscarded
    io.memoryForwarded         := backend.io.memoryForwarded
    backend.io.allocate(0)     := io.allocate0
    backend.io.allocate(1)     := io.allocate1
    backend.io.rawRequests.foreach { raw =>
        raw(0) := io.allocate0.bits.rename
        raw(1) := io.allocate1.bits.rename
    }
    backend.io.fetchFaultMask.foreach(_ := 0.U)
    io.renamed0                := backend.io.renamed(0)
    io.renamed1                := backend.io.renamed(1)
    io.commit0                 := backend.io.commit(0)
    io.commit1                 := backend.io.commit(1)
    io.issued0                 := backend.io.issued(0)
    io.issued1                 := backend.io.issued(1)
    backend.io.commitEnable    := io.commitEnable
    backend.io.recover         := io.recover
    backend.io.inspectRegister := io.inspectRegister
    io.recoveryAccepted        := backend.io.recoveryAccepted
    io.recovering              := backend.io.recovering
    io.occupancy               := backend.io.occupancy
    io.headException           := backend.io.headException
    io.committedValue          := backend.io.committedValue
    io.redirect                := backend.io.redirect
}

object LoadIssueForwardingGsimMain extends App {
    val target = args.headOption.getOrElse("build/gsim/integer")
    val p = BoardSocConfig.timingParams("staged-load-issue").copy(
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 4096)
    ChiselStage.emitCHIRRTLFile(new LoadIssueForwardingGsim(p), Array("--target-dir", target))
}
