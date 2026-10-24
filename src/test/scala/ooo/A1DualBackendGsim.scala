package soc.core.ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.platform.CommonCpuProfile

class BranchExecutionObservation(p: OooParams) extends Bundle {
    val occupied = Bool()
    val token = new RobToken(p)
    val pc = UInt(64.W)
    val control = Bool()
    val resolved = Bool()
    val cancel = Bool()
    val wbAccepted = Bool()
    val enq = Bool()
    val incomingToken = new RobToken(p)
    val incomingControl = Bool()
}

/** Real A1 backend parameters, with an explicit decoded-instruction test boundary.
  * No frontend, TLB, cache, bus, or FPGA performance claim follows from this
  * fixture. M-mode/Bare memory service is external, ordered, and backpressurable.
  * F/D, Sv39, PMP, token width, storage, and capacities are NOT edited away.
  */
class A1DualBackendGsim(topology: String, branchTopology: String = "writeback-coupled") extends Module {
    val config = CommonCpuProfile.A1.fpga.copy(completionTopology = topology,
        branchResolutionTopology = branchTopology)
    val p = config.coreParams
    require(p.machineSystem && p.fpEnabled && p.pmpEntries == 16 && p.virtualMemoryLevels == 3)
    require(p.robEntries == 16 && p.physicalRegs == 48 && p.memoryEntries == 2 && p.tagBits == 64)
    require(p.cpuReturnConfig.isEmpty && !p.virtualRamLoadPrecheck && !p.postedStoreMerge)
    val io = IO(new Bundle {
        val valid0 = Input(Bool())
        val valid1 = Input(Bool())
        val instruction0 = Input(UInt(32.W))
        val instruction1 = Input(UInt(32.W))
        val pc0 = Input(UInt(64.W))
        val pc1 = Input(UInt(64.W))
        val commitEnable = Input(Bool())
        val faultMask = Input(UInt(2.W))
        val pageFaultMask = Input(UInt(2.W))
        val inspectRegister = Input(UInt(5.W))
        val committedValue = Output(UInt(64.W))
        val renamed0 = Output(Bool())
        val renamed1 = Output(Bool())
        val commit0 = Output(Valid(new CommitRecord(p)))
        val commit1 = Output(Valid(new CommitRecord(p)))
        val trap = Output(Valid(new HeadException(p)))
        val redirect = Output(Valid(new FrontendRedirect(p)))
        val memory = new DataPort
        val issueCount = Output(UInt(2.W))
        val memoryBusy = Output(Bool())
        val occupancy = Output(UInt(p.countBits.W))
        val ownersIdle = Output(Bool())
        val dualSideStart = Output(Bool())
        val dualSideComplete = Output(Bool())
        val systemAndOtherComplete = Output(Bool())
        val exchangedOperands = Output(Bool())
        val aluHeldForward = Output(Bool())
        val loadHeldForward = Output(Bool())
        val mulDivCancelled = Output(Bool())
        val mulDivMultiCancel = Output(Bool())
        val branchMailboxOccupied = Output(Bool())
        val branchMailboxValid = Output(Bool())
        val branchMailboxReady = Output(Bool())
        val branchMailboxCapture = Output(UInt(2.W))
        val branchMailboxDrop = Output(Bool())
        val branchMailboxToken = Output(new RobToken(p))
        val branchMailboxPc = Output(UInt(64.W))
        val branchMailboxTarget = Output(UInt(64.W))
        val branchCapture = Output(Valid(new FrontendRedirect(p)))
        val branchCaptureLane = Output(Bool())
        val branchOffer0 = Output(Valid(new FrontendRedirect(p)))
        val branchOffer1 = Output(Valid(new FrontendRedirect(p)))
        val branchHead = Output(UInt(p.robBits.W))
        val branchMemoryProtected = Output(Bool())
        val branchSystemProtected = Output(Bool())
        val branchMemoryOwner = Output(new RobToken(p))
        val branchSystemOwner = Output(new RobToken(p))
        val branchSource0 = Output(new BranchExecutionObservation(p))
        val branchSource1 = Output(new BranchExecutionObservation(p))
    })
    val branchSources = Seq(io.branchSource0, io.branchSource1)
    val branchOffers = Seq(io.branchOffer0, io.branchOffer1)
    val backend = Module(new IntegerBackend(p))
    val rawRequests = Wire(Vec(2, new RenameRequest))
    val requests = (0 until 2).map { lane =>
        val decode = Module(new IntegerDecode(p.machineSystem, p.atomicMemory, p.parallelDecodeLegality,
            p.parallelBitLegality, p.fpEnabled, p.fpConfig))
        decode.io.pc := Seq(io.pc0, io.pc1)(lane)
        decode.io.instruction := Seq(io.instruction0, io.instruction1)(lane)
        val request = Wire(Valid(new IntegerRequest))
        request.valid := Seq(io.valid0, io.valid1)(lane)
        request.bits := decode.io.decoded
        rawRequests(lane) := decode.io.decoded.rename
        // Match the real frontend's authorized fault-rename mask while keeping
        // the decoded control class as a deliberately stronger backend input:
        // even legal branch bytes with a fetch fault may not offer a redirect.
        when(io.faultMask(lane) || io.pageFaultMask(lane)) {
            request.bits.rename.writesRd := false.B
            request.bits.rename.rd := 0.U
            request.bits.rename.rs1 := 0.U
            request.bits.rename.rs2 := 0.U
        }
        request.bits.fetchFault := io.faultMask(lane)
        request.bits.fetchPageFault := io.pageFaultMask(lane)
        request.bits.fetchTval := Seq(io.pc0, io.pc1)(lane)
        request
    }
    backend.io.allocate := VecInit(requests)
    backend.io.rawDestinations.foreach(_ := VecInit(rawRequests.map(_.rd)))
    backend.io.rawRequests.foreach(_ := rawRequests)
    backend.io.fetchFaultMask.foreach(_ := io.faultMask | io.pageFaultMask)
    backend.io.commitEnable := io.commitEnable
    backend.io.recover := 0.U.asTypeOf(backend.io.recover)
    backend.io.inspectRegister := io.inspectRegister
    backend.io.imsic.get.request.ready := true.B
    backend.io.imsic.get.response.valid := false.B
    backend.io.imsic.get.response.bits := 0.U.asTypeOf(backend.io.imsic.get.response.bits)
    backend.io.externalInterrupt.get := false.B
    backend.io.supervisorExternalInterrupt.get := false.B
    backend.io.timerInterrupt.get := false.B
    backend.io.timeValue.get := 0.U
    backend.io.emptyPc.get := io.pc0
    backend.io.fetchQuiescent.get := true.B
    backend.io.fenceIFlushReady.get := true.B
    backend.io.vmFlushReady.get := true.B
    backend.io.externalPrefetchBusy.foreach(_ := false.B)
    io.memory <> backend.io.memory
    io.renamed0 := backend.io.renamed(0).valid
    io.renamed1 := backend.io.renamed(1).valid
    io.commit0 := backend.io.commit(0)
    io.commit1 := backend.io.commit(1)
    io.trap := backend.io.trap.get
    io.redirect := backend.io.redirect
    io.issueCount := backend.io.issueCount
    io.memoryBusy := backend.io.memoryBusy
    io.occupancy := backend.io.occupancy
    io.ownersIdle := backend.io.ownersIdle
    io.committedValue := backend.io.committedValue
    io.mulDivCancelled := backend.io.mulDivCancelled
    io.mulDivMultiCancel := backend.io.mulDivMultiCancel
    def fire(port: DecoupledIO[_ <: Data]): Bool = BoringUtils.bore(port.valid) && BoringUtils.bore(port.ready)
    io.dualSideStart := fire(backend.lsu.io.start) &&
        (fire(backend.multiplier.io.start) || fire(backend.mulDiv.io.start))
    io.dualSideComplete := PopCount(Seq(fire(backend.lsu.io.complete), fire(backend.multiplier.io.complete),
        fire(backend.mulDiv.io.complete), fire(backend.systemComplete))) === 2.U
    io.systemAndOtherComplete := fire(backend.systemComplete) &&
        PopCount(backend.io.issued.map(_.valid)) === 2.U
    io.exchangedOperands := BoringUtils.bore(backend.exchangeExecutionInputs) &&
        BoringUtils.bore(backend.executionEnqueued).asUInt.orR
    val captured = BoringUtils.bore(backend.executionEnqueued)
    val dispatched = BoringUtils.bore(backend.dispatched)
    val sources1 = VecInit(backend.issueEntries.map(e => BoringUtils.bore(e.renamed.source1)))
    val sources2 = VecInit(backend.issueEntries.map(e => BoringUtils.bore(e.renamed.source2)))
    val uses1 = VecInit(backend.issueEntries.map(e => !BoringUtils.bore(e.request.usePc)))
    val uses2 = VecInit(backend.issueEntries.map(e => !BoringUtils.bore(e.request.useImmediate)))
    io.aluHeldForward := (0 until 2).map { rank =>
        val index = Mux(captured(rank), dispatched(rank).bits, 0.U)
        captured(rank) && backend.executionStages.indices.map { lane =>
            val wake = BoringUtils.bore(backend.executionWake(lane))
            wake.valid && !BoringUtils.bore(backend.executionStages(lane).io.deq.ready) &&
                ((uses1(index) && sources1(index) === wake.bits) ||
                    (uses2(index) && sources2(index) === wake.bits))
        }.reduce(_ || _)
    }.reduce(_ || _)
    io.loadHeldForward := backend.io.loadIssueForwarded.get.asUInt.orR &&
        !BoringUtils.bore(backend.lsu.io.complete.ready)
    io.branchMailboxOccupied := false.B
    io.branchMailboxValid := false.B
    io.branchMailboxReady := false.B
    io.branchMailboxCapture := 0.U
    io.branchMailboxDrop := false.B
    io.branchMailboxToken := 0.U.asTypeOf(new RobToken(p))
    io.branchMailboxPc := 0.U
    io.branchMailboxTarget := 0.U
    io.branchCapture := 0.U.asTypeOf(io.branchCapture)
    io.branchCaptureLane := false.B
    branchOffers.foreach(offer => offer := 0.U.asTypeOf(offer))
    io.branchHead := 0.U
    io.branchMemoryProtected := false.B
    io.branchSystemProtected := false.B
    io.branchMemoryOwner := 0.U.asTypeOf(new RobToken(p))
    io.branchSystemOwner := 0.U.asTypeOf(new RobToken(p))
    branchSources.foreach(source => source := 0.U.asTypeOf(source))
    backend.branchMailbox.foreach { mailbox =>
        val capture = BoringUtils.bore(mailbox.io.capture)
        val offers = BoringUtils.bore(mailbox.io.offer)
        io.branchMailboxOccupied := BoringUtils.bore(mailbox.io.occupied)
        io.branchMailboxValid := BoringUtils.bore(mailbox.io.out.valid)
        io.branchMailboxReady := BoringUtils.bore(mailbox.io.out.ready)
        io.branchMailboxCapture := capture
        io.branchMailboxDrop := BoringUtils.bore(backend.branchMailboxDropped)
        io.branchMailboxToken := BoringUtils.bore(mailbox.io.out.bits.token)
        io.branchMailboxPc := BoringUtils.bore(mailbox.io.out.bits.pc)
        io.branchMailboxTarget := BoringUtils.bore(mailbox.io.out.bits.target)
        io.branchCapture.valid := capture.orR
        io.branchCapture.bits := Mux1H((0 until 2).map(lane => capture(lane) -> offers(lane).bits))
        io.branchCaptureLane := capture(1)
        branchOffers.zipWithIndex.foreach { case (offer, lane) => offer := offers(lane) }
        io.branchHead := BoringUtils.bore(backend.head)
        io.branchMemoryProtected := BoringUtils.bore(backend.memoryProtected)
        io.branchSystemProtected := BoringUtils.bore(backend.systemProtected)
        io.branchMemoryOwner := BoringUtils.bore(backend.memoryOwner)
        io.branchSystemOwner := BoringUtils.bore(backend.systemOwner)
        for (lane <- 0 until 2) {
            val stage = backend.executionStages(lane)
            val operands = BoringUtils.bore(stage.io.deq.bits).asTypeOf(new IntegerExecutionOperands(p))
            val incoming = BoringUtils.bore(stage.io.enq.bits).asTypeOf(new IntegerExecutionOperands(p))
            branchSources(lane).occupied := BoringUtils.bore(stage.io.occupied)
            branchSources(lane).token := operands.entry.renamed.token
            branchSources(lane).pc := operands.entry.request.rename.pc
            branchSources(lane).control := operands.entry.request.controlFlow =/= ControlFlow.none
            branchSources(lane).resolved := BoringUtils.bore(stage.io.resolved.get)
            branchSources(lane).cancel := BoringUtils.bore(stage.io.cancel)
            branchSources(lane).wbAccepted := fire(stage.io.deq)
            branchSources(lane).enq := fire(stage.io.enq)
            branchSources(lane).incomingToken := incoming.entry.renamed.token
            branchSources(lane).incomingControl := incoming.entry.request.controlFlow =/= ControlFlow.none
        }
    }
}

object A1DualBackendGsimMain extends App {
    val topology = args.lift(1).getOrElse("legacy")
    val branchTopology = args.lift(2).getOrElse("writeback-coupled")
    val config = CommonCpuProfile.A1.fpga.copy(completionTopology = topology,
        branchResolutionTopology = branchTopology)
    val p = config.coreParams
    val target = java.nio.file.Paths.get(args.head)
    java.nio.file.Files.createDirectories(target)
    val fields = p.productElementNames.zip(p.productIterator).map { case (key, value) =>
        s"\"$key\":\"${value.toString.replace("\\", "\\\\").replace("\"", "\\\"")}\""
    }.mkString(",\n")
    java.nio.file.Files.writeString(target.resolve("effective-parameters.json"), s"{\n$fields\n}\n")
    ChiselStage.emitCHIRRTLFile(new A1DualBackendGsim(topology, branchTopology), Array("--target-dir", args.head))
}
