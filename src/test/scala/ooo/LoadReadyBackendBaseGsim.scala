package ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Scalar test ports for the pinned GSIM accessor API. */
class LoadReadyBackendBaseGsim(p: OooParams, eventBoundReplies: Boolean = false) extends Module {
    require(p.renameWidth == 2 && p.commitWidth == 2 && p.completionWidth == 2)
    if (eventBoundReplies) {
        require(!p.fastHeadLoadRetire && !p.fastBufferedStoreRetire && !p.loadCompletionBypass &&
            !p.mulWordPreviewBypass && !p.machineSystem && p.virtualMemoryLevels == 0 &&
            !p.taggedStoreReturns && !p.canonicalVirtualStoreOverlap && !p.virtualRamLoadPrecheck &&
            !p.postedStoreMerge && !p.memoryProofFrontier && p.registeredMemoryRequests &&
            p.registeredMemoryAddress && p.registeredLoadIssueForwarding && p.memoryEntries == 4,
            "event-bound response gate needs the independently reviewed no-loop bare profile")
    }

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
    // Test-only legal environment service gate. It can withhold an already owed
    // external response, never a production start/completion/issue grant.
    val responseOnStart = if (eventBoundReplies) Some(IO(Input(Valid(new RobToken(p))))) else None
    val responseServiceGate = if (eventBoundReplies) Some(IO(Output(Bool()))) else None
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
    if (eventBoundReplies) {
        val started = BoringUtils.bore(backend.lsu.io.start.valid) && BoringUtils.bore(backend.lsu.io.start.ready)
        val startedToken = BoringUtils.bore(backend.lsu.io.start.bits.token)
        val gate = !responseOnStart.get.valid || (started && startedToken.asUInt === responseOnStart.get.bits.asUInt)
        responseServiceGate.get := gate
        when(responseOnStart.get.valid && io.memory.response.valid && gate) {
            assert(backend.io.memory.response.ready,
                "one-edge armed response release must consume its already owed reply")
            val start = BoringUtils.bore(backend.lsu.io.start.bits)
            assert(!start.store && !start.atomic && start.size === 3.U && start.address(2, 0) =/= 0.U,
                "armed event release must be the exact misaligned ordinary XLEN F start")
            for (slot <- backend.lsu.slots) {
                val request = BoringUtils.bore(slot.io.memory.request.valid)
                val token = BoringUtils.bore(slot.io.start.bits.token)
                val firing = BoringUtils.bore(slot.io.start.valid) && BoringUtils.bore(slot.io.start.ready)
                when(firing && token.asUInt === responseOnStart.get.bits.asUInt) {
                    assert(!request, "local misaligned F must issue no external memory request")
                }
            }
        }
        io.memory.request <> backend.io.memory.request
        backend.io.memory.response.valid := io.memory.response.valid && gate
        backend.io.memory.response.bits := io.memory.response.bits
        io.memory.response.ready := backend.io.memory.response.ready && gate
    } else { io.memory <> backend.io.memory }
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

