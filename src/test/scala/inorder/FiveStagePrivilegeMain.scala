package inorder

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.inorder._

/** Scalar GSIM adapter; architectural configuration is not inferred by the software oracle. */
class FiveStagePrivilegeHarness(timingCuts: Boolean = false) extends Module {
    val p = FiveStageConfig(withUser = true, withSupervisor = true, withSv39 = true, pmpEntries = 4,
        fpgaTimingCuts = timingCuts, pipelineProfile = if (timingCuts) "fpga8" else "compact5")
    val io = IO(new Bundle {
        val readAddress = Input(UInt(12.W)); val readData = Output(UInt(64.W)); val readLegal = Output(Bool())
        val readDataForWrite = Output(UInt(64.W))
        val writeValid = Input(Bool()); val writeAddress = Input(UInt(12.W)); val writeData = Input(UInt(64.W))
        val trapValid = Input(Bool()); val trapPc = Input(UInt(64.W))
        val trapCause = Input(UInt(64.W)); val trapTval = Input(UInt(64.W))
        val mret = Input(Bool()); val sret = Input(Bool()); val sfence = Input(Bool())
        val externalIrq = Input(Bool()); val supervisorExternalIrq = Input(Bool())
        val softwareIrq = Input(Bool()); val timerIrq = Input(Bool())
        val irqPending = Output(Bool()); val irqCause = Output(UInt(64.W)); val vector = Output(UInt(64.W))
        val privilege = Output(UInt(2.W)); val dataPrivilege = Output(UInt(2.W)); val satp = Output(UInt(64.W))
        val mretLegal = Output(Bool()); val sretLegal = Output(Bool()); val sfenceLegal = Output(Bool())
        val wfiLegal = Output(Bool()); val invalidate = Output(Bool()); val barrier = Output(Bool())
        val address = Input(UInt(64.W)); val size = Input(UInt(4.W)); val accessPrivilege = Input(UInt(2.W))
        val execute = Input(Bool()); val writeAccess = Input(Bool()); val allow = Output(Bool())
    })
    val csr = Module(new FiveStageMachineState(p))
    csr.io.readAddress := io.readAddress; io.readData := csr.io.readData; io.readLegal := csr.io.readLegal
    io.readDataForWrite := csr.io.readDataForWrite
    csr.io.write.valid := io.writeValid; csr.io.write.bits.address := io.writeAddress
    csr.io.write.bits.data := io.writeData; csr.io.retire := false.B; csr.io.time := 123.U
    csr.io.fpRetire := false.B; csr.io.fpFlags := 0.U
    csr.io.trap.valid := io.trapValid; csr.io.trap.bits.pc := io.trapPc
    csr.io.trap.bits.cause := io.trapCause; csr.io.trap.bits.tval := io.trapTval
    csr.io.mret := io.mret; csr.io.sret := io.sret; csr.io.sfence := io.sfence
    csr.io.externalIrq := io.externalIrq; csr.io.supervisorExternalIrq := io.supervisorExternalIrq
    csr.io.softwareIrq := io.softwareIrq; csr.io.timerIrq := io.timerIrq
    io.irqPending := csr.io.irqPending; io.irqCause := csr.io.irqCause; io.vector := csr.io.trapPc
    io.privilege := csr.io.context.privilege; io.dataPrivilege := csr.io.context.dataPrivilege
    io.satp := csr.io.context.satp; io.mretLegal := csr.io.mretLegal; io.sretLegal := csr.io.sretLegal
    io.sfenceLegal := csr.io.sfenceLegal; io.wfiLegal := csr.io.wfiLegal
    io.invalidate := csr.io.invalidateTranslation; io.barrier := csr.io.contextBarrier
    val pmp = Module(new FiveStagePmp(p))
    pmp.io.entries := csr.io.pmp; pmp.io.address := io.address; pmp.io.size := io.size
    pmp.io.privilege := io.accessPrivilege; pmp.io.execute := io.execute; pmp.io.write := io.writeAccess
    io.allow := pmp.io.allow
}

class FiveStageTranslationHarness(instruction: Boolean = false, fastData: Boolean = false,
    timingCuts: Boolean = false, atomic: Boolean = false, window: String = "aligned",
    tlb: Int = 4, fastInstruction: Boolean = true, overlapRetirement: Boolean = false,
    splitCandidates: Boolean = false, splitDataCandidates: Boolean = false, directData: Boolean = false,
    indexedDataProofs: Boolean = false, replyHandoff: Boolean = false,
    bankedTlbProofs: Boolean = false) extends Module {
    require(Set("aligned", "shifted", "board").contains(window))
    val p = FiveStageConfig(withUser = true, withSupervisor = true, withSv39 = true, pmpEntries = 4,
        withA = atomic, pipelineProfile = if (timingCuts) "fpga8" else "compact5",
        fpgaTimingCuts = timingCuts, fastDataTranslation = fastData, tlbEntries = tlb,
        directFastDataIssue = directData, indexedDataProofs = indexedDataProofs,
        dataReplyHandoff = replyHandoff, bankedTlbProofs = bankedTlbProofs,
        fastInstructionTranslation = fastInstruction,
        earlyMemoryIssue = overlapRetirement, overlapDataRetirement = overlapRetirement,
        cacheableBase = BigInt(if (window == "shifted") "80000040" else
            if (window == "board") "80200000" else "80000000", 16),
        cacheableBytes = if (window == "board") BigInt(1) << 31 else BigInt("10000000", 16))
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new FiveStageDataRequest(p)))
        val response = Decoupled(new FiveStageDataResponse(p))
        val physicalRequest = Decoupled(new FiveStageDataRequest(p))
        val physicalResponse = Flipped(Decoupled(new FiveStageDataResponse(p)))
        val walkRequest = Decoupled(new FiveStageDataRequest(p))
        val walkResponse = Flipped(Decoupled(new FiveStageDataResponse(p)))
        val privilege = Input(UInt(2.W)); val dataPrivilege = Input(UInt(2.W))
        val satp = Input(UInt(64.W)); val sum = Input(Bool()); val mxr = Input(Bool())
        val pmpTop = Input(UInt(34.W)); val pmpConfig = Input(UInt(8.W))
        val invalidate = Input(Bool()); val hit = Output(Bool()); val miss = Output(Bool())
        val physicalCacheable = if (instruction && timingCuts) Some(Output(Bool())) else None
        val candidate0 = if (splitCandidates) Some(Input(UInt(64.W))) else None
        val candidate1 = if (splitCandidates) Some(Input(UInt(64.W))) else None
        val candidateSecond = if (splitCandidates) Some(Input(Bool())) else None
        val dataCandidate0 = if (splitDataCandidates) Some(Input(new FiveStageDataRequest(p))) else None
        val dataCandidate1 = if (splitDataCandidates) Some(Input(new FiveStageDataRequest(p))) else None
        val dataCandidateEarly = if (splitDataCandidates) Some(Input(Bool())) else None
        val readAhead = if (replyHandoff) Some(Input(Bool())) else None
    })
    val dut = Module(new FiveStageAddressTranslation(p, instruction, splitCandidates, splitDataCandidates))
    dut.io.addressCandidates.foreach { a =>
        a(0) := io.candidate0.get
        a(1) := io.candidate1.get
    }
    dut.io.candidateSecond.foreach(_ := io.candidateSecond.get)
    dut.io.dataCandidates.foreach { candidates =>
        candidates(0) := io.dataCandidate0.get; candidates(1) := io.dataCandidate1.get
    }
    dut.io.dataCandidateEarly.foreach(_ := io.dataCandidateEarly.get)
    dut.io.readAhead.foreach(_ := io.readAhead.get)
    dut.io.request <> io.request; io.response <> dut.io.response
    io.physicalRequest <> dut.io.physical.request; dut.io.physical.response <> io.physicalResponse
    io.walkRequest <> dut.io.walk.request; dut.io.walk.response <> io.walkResponse
    dut.io.context.privilege := io.privilege; dut.io.context.dataPrivilege := io.dataPrivilege
    dut.io.context.satp := io.satp; dut.io.context.sum := io.sum; dut.io.context.mxr := io.mxr
    dut.io.context.pmpAllOff := io.pmpConfig(4, 3) === 0.U
    dut.io.entries.foreach { e => e.config := 0.U; e.address := 0.U; e.lower := 0.U; e.upper := 0.U }
    dut.io.entries(0).config := io.pmpConfig; dut.io.entries(0).address := io.pmpTop
    dut.io.entries(0).lower := 0.U; dut.io.entries(0).upper := io.pmpTop << 2
    dut.io.invalidate := io.invalidate; io.hit := dut.io.hit; io.miss := dut.io.miss
    io.physicalCacheable.foreach(_ := dut.io.physicalCacheable.get)
}

object FiveStagePrivilegeMain extends App {
    ChiselStage.emitCHIRRTLFile(new FiveStagePrivilegeHarness(args.contains("--timing-cuts")),
        Array("--target-dir", args.head))
}
object FiveStageTranslationMain extends App {
    ChiselStage.emitCHIRRTLFile(new FiveStageTranslationHarness(args.contains("--instruction"),
        args.contains("--fast-data-translation"), args.contains("--timing-cuts"), args.contains("--atomic"),
        args.find(_.startsWith("--window=")).map(_.stripPrefix("--window=")).getOrElse("aligned"),
        args.find(_.startsWith("--tlb=")).map(_.stripPrefix("--tlb=")).map(_.toInt).getOrElse(4),
        !args.contains("--no-fast-instruction"), args.contains("--overlap-data-retirement"),
        args.contains("--split-candidates"), args.contains("--split-data-candidates"),
        args.contains("--direct-fast-data-issue"), args.contains("--indexed-data-proofs"),
        args.contains("--data-reply-handoff"), args.contains("--banked-tlb-proofs")),
        Array("--target-dir", args.head))
}
