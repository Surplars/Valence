package soc.core.ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.platform.CommonCpuProfile

/** Real A1 backend parameters, with an explicit decoded-instruction test boundary.
  * No frontend, TLB, cache, bus, or FPGA performance claim follows from this
  * fixture. M-mode/Bare memory service is external, ordered, and backpressurable.
  * F/D, Sv39, PMP, token width, storage, and capacities are NOT edited away.
  */
class A1DualBackendGsim(topology: String) extends Module {
    val config = CommonCpuProfile.A1.fpga.copy(completionTopology = topology)
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
    })
    val backend = Module(new IntegerBackend(p))
    val requests = (0 until 2).map { lane =>
        val decode = Module(new IntegerDecode(p.machineSystem, p.atomicMemory, p.parallelDecodeLegality,
            p.parallelBitLegality, p.fpEnabled, p.fpConfig))
        decode.io.pc := Seq(io.pc0, io.pc1)(lane)
        decode.io.instruction := Seq(io.instruction0, io.instruction1)(lane)
        val request = Wire(Valid(new IntegerRequest))
        request.valid := Seq(io.valid0, io.valid1)(lane)
        request.bits := decode.io.decoded
        request
    }
    backend.io.allocate := VecInit(requests)
    backend.io.rawDestinations.foreach(_ := VecInit(requests.map(_.bits.rename.rd)))
    backend.io.rawRequests.foreach(_ := VecInit(requests.map(_.bits.rename)))
    backend.io.fetchFaultMask.foreach(_ := 0.U)
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
}

object A1DualBackendGsimMain extends App {
    val topology = args.lift(1).getOrElse("legacy")
    val config = CommonCpuProfile.A1.fpga.copy(completionTopology = topology)
    val p = config.coreParams
    val target = java.nio.file.Paths.get(args.head)
    java.nio.file.Files.createDirectories(target)
    val fields = p.productElementNames.zip(p.productIterator).map { case (key, value) =>
        s"\"$key\":\"${value.toString.replace("\\", "\\\\").replace("\"", "\\\"")}\""
    }.mkString(",\n")
    java.nio.file.Files.writeString(target.resolve("effective-parameters.json"), s"{\n$fields\n}\n")
    ChiselStage.emitCHIRRTLFile(new A1DualBackendGsim(topology), Array("--target-dir", args.head))
}
