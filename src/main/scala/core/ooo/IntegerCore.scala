package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.isa.Compressed

/** Bare integer/control-flow/load-store core with bimodal conditional-branch prediction, not a complete RV64I
  * processor. The instruction source supplies a contiguous prefix from fetchPc each cycle. Accepted lanes
  * advance the PC or take their predicted branch; unaccepted words must be presented again for the new PC. This is a
  * combinational supply interface, not an asynchronous cache response protocol. The baseline stops on exceptions;
  * machineSystem enables CSR execution and synchronous/external interrupt trap entry. Target: renameWidth
  * instructions/cycle with no fetch bubbles when supply and backend capacity permit.
  */
class IntegerCore(val p: OooParams = OooParams(), resetPc: BigInt = BigInt("80000000", 16)) extends Module {
    require(resetPc >= 0 && resetPc < (BigInt(1) << 64) && resetPc % (if (p.compressedInstructions) 2 else 4) == 0)
    val io = IO(new Bundle {
        val imsic                       = if (p.machineSystem) Some(new MachineCsrPort) else None
        val externalInterrupt           = if (p.machineSystem) Some(Input(Bool())) else None
        val supervisorExternalInterrupt = if (p.machineSystem) Some(Input(Bool())) else None
        val timerInterrupt              = if (p.machineSystem) Some(Input(Bool())) else None
        val timeValue                   = if (p.machineSystem) Some(Input(UInt(64.W))) else None
        val trap                        = if (p.machineSystem) Some(Output(Valid(new HeadException(p)))) else None
        val instructions                = Input(Vec(p.renameWidth, Valid(UInt(32.W))))
        val instructionFaults           = Input(Vec(p.renameWidth, Bool()))
        val instructionPageFaults       = Input(Vec(p.renameWidth, Bool()))
        val instructionFaultAddresses   = if (p.compressedInstructions)
            Some(Input(Vec(p.renameWidth, UInt(64.W)))) else None
        val fetchPc                     = Output(UInt(64.W))
        val pmpState                    = if (p.pmpEntries > 0) Some(Output(new PmpState)) else None
        val fetchPrivilege              = if (p.pmpEntries > 0) Some(Output(UInt(2.W))) else None
        val fetchQuiescent               = if (p.pmpEntries > 0) Some(Input(Bool())) else None
        val pauseFetch                   = if (p.pmpEntries > 0) Some(Output(Bool())) else None
        val vmState                     = if (p.virtualMemoryLevels > 0) Some(Output(new VmCsrState)) else None
        val vmFlush                     = if (p.virtualMemoryLevels > 0) Some(Output(Bool())) else None
        val vmFlushReady                = if (p.virtualMemoryLevels > 0) Some(Input(Bool())) else None
        val fenceIFlush                 = if (p.machineSystem) Some(Output(Bool())) else None
        val fenceIFlushReady            = if (p.machineSystem) Some(Input(Bool())) else None
        val accepted                    = Output(Vec(p.renameWidth, Bool()))
        val commitEnable                = Input(Bool())
        val commit                      = Output(Vec(p.commitWidth, Valid(new CommitRecord(p))))
        val exception                   = Output(Valid(new HeadException(p)))
        val occupancy                   = Output(UInt(p.countBits.W))
        val headProfile                 = Output(new HeadProfile)
        val inspectRegister             = Input(UInt(5.W))
        val committedValue              = Output(UInt(64.W))
        val redirect                    = Output(Valid(new FrontendRedirect(p)))
        val invalidateFetch             = Output(Bool())
        val recovering                  = Output(Bool())
        val memory                      = new DataPort
        val memoryBusy                  = Output(Bool())
        val issueCount                  = Output(UInt(log2Ceil(p.issueWidth + 1).W))
        val memoryDiscarded             = Output(Bool())
        val memoryForwarded             = Output(Bool())
        val mulDivCancelled             = Output(Bool())
        val mulDivOverlap               = Output(Bool())
        val mulDivBlocked               = Output(Bool())
        val mulDivConcurrent            = Output(Bool())
        val mulDivMultiCancel           = Output(Bool())
    })
    val backend = Module(new IntegerBackend(p))
    if (p.machineSystem) {
        io.imsic.get <> backend.io.imsic.get
        io.fenceIFlush.get := backend.io.fenceIFlush.get
        backend.io.fenceIFlushReady.get := io.fenceIFlushReady.get
        io.trap.get                                := backend.io.trap.get
        backend.io.externalInterrupt.get           := io.externalInterrupt.get
        backend.io.supervisorExternalInterrupt.get := io.supervisorExternalInterrupt.get
        backend.io.timerInterrupt.get              := io.timerInterrupt.get
        backend.io.timeValue.get                   := io.timeValue.get
    }
    if (p.pmpEntries > 0) {
        io.pmpState.get := backend.io.pmpState.get
        io.fetchPrivilege.get := backend.io.fetchPrivilege.get
        backend.io.fetchQuiescent.get := io.fetchQuiescent.get
        io.pauseFetch.get := backend.io.pauseFetch.get
    }
    if (p.virtualMemoryLevels > 0) {
        io.vmState.get := backend.io.vmState.get
        io.vmFlush.get := backend.io.vmFlush.get
        backend.io.vmFlushReady.get := io.vmFlushReady.get
    }
    io.memory <> backend.io.memory
    io.memoryBusy        := backend.io.memoryBusy
    io.issueCount        := backend.io.issueCount
    io.memoryDiscarded   := backend.io.memoryDiscarded
    io.memoryForwarded   := backend.io.memoryForwarded
    io.mulDivCancelled   := backend.io.mulDivCancelled
    io.mulDivOverlap     := backend.io.mulDivOverlap
    io.mulDivBlocked     := backend.io.mulDivBlocked
    io.mulDivConcurrent  := backend.io.mulDivConcurrent
    io.mulDivMultiCancel := backend.io.mulDivMultiCancel
    val pc = RegInit(resetPc.U(64.W))
    if (p.machineSystem) { backend.io.emptyPc.get := pc }
    io.fetchPc                 := pc
    backend.io.commitEnable    := io.commitEnable
    backend.io.recover         := 0.U.asTypeOf(Valid(new RecoveryRequest(p)))
    backend.io.inspectRegister := io.inspectRegister
    io.commit                  := backend.io.commit
    io.exception               := backend.io.headException
    io.occupancy               := backend.io.occupancy
    io.headProfile             := backend.io.headProfile
    io.committedValue          := backend.io.committedValue
    io.redirect                := backend.io.redirect
    io.invalidateFetch         := backend.io.invalidateFetch
    io.recovering              := backend.io.recovering
    val predictor = Module(new BranchPredictor(p))
    val indirectPredictor = if (p.indirectTargetEntries > 0)
        Some(Module(new IndirectTargetPredictor(p))) else None
    for (lane <- 0 until p.commitWidth) {
        val commit = io.commit(lane)
        val compressedBranch = p.compressedInstructions.B &&
            commit.bits.instruction(1, 0) =/= 3.U &&
            (commit.bits.instruction(15, 13) === 6.U || commit.bits.instruction(15, 13) === 7.U) &&
            commit.bits.instruction(1, 0) === 1.U
        predictor.io.train(lane).valid      := commit.valid &&
            (commit.bits.instruction(6, 0) === "h63".U || compressedBranch)
        predictor.io.train(lane).bits.pc    := commit.bits.pc
        predictor.io.train(lane).bits.taken := commit.bits.nextPc =/= commit.bits.pc +
            Mux(p.compressedInstructions.B && commit.bits.instruction(1, 0) =/= 3.U, 2.U, 4.U)
        indirectPredictor.foreach { table =>
            val inst = commit.bits.instruction
            val compressedJalr = p.compressedInstructions.B && inst(1, 0) === 2.U &&
                inst(15, 13) === 4.U && inst(6, 2) === 0.U && inst(11, 7) =/= 0.U
            val regularJalr = inst(6, 0) === "h67".U && inst(14, 12) === 0.U && inst(1, 0) === 3.U
            table.io.train(lane).valid := commit.valid && (regularJalr || compressedJalr)
            table.io.train(lane).bits.pc := commit.bits.pc
            table.io.train(lane).bits.target := commit.bits.nextPc
        }
    }
    val returnTop = WireDefault(0.U(64.W))
    val returnAvailable = WireDefault(false.B)
    if (p.compressedInstructions) {
        val depth = p.returnStackEntries
        val top = RegInit(0.U(log2Ceil(depth).W))
        val count = RegInit(0.U(log2Ceil(depth + 1).W))
        val entries = Reg(Vec(depth, UInt(64.W)))
        returnAvailable := count =/= 0.U
        returnTop := entries(top - 1.U)
        var nextTop = top
        var nextCount = count
        for (lane <- 0 until p.commitWidth) {
            val commit = io.commit(lane)
            val inst = commit.bits.instruction
            val short = inst(1, 0) =/= 3.U
            val linkRd = commit.bits.rd === 1.U || commit.bits.rd === 5.U
            val linkRs1 = inst(19, 15) === 1.U || inst(19, 15) === 5.U
            val compressedControl = short && inst(1, 0) === 2.U && inst(15, 13) === 4.U &&
                inst(6, 2) === 0.U && inst(11, 7) =/= 0.U
            val call = commit.valid && ((short && compressedControl && inst(12)) ||
                (!short && linkRd && commit.bits.writesRd &&
                    (inst(6, 0) === "h6f".U || inst(6, 0) === "h67".U)))
            val ret = commit.valid && !call &&
                ((short && compressedControl && !inst(12) &&
                    (inst(11, 7) === 1.U || inst(11, 7) === 5.U)) ||
                (!short && inst(6, 0) === "h67".U && inst(14, 12) === 0.U &&
                    inst(11, 7) === 0.U && linkRs1 && inst(31, 20) === 0.U))
            val pop = ret && nextCount =/= 0.U
            when(call) { entries(nextTop) := commit.bits.data }
            nextTop = Mux(call, nextTop + 1.U, Mux(pop, nextTop - 1.U, nextTop))
            nextCount = Mux(call, Mux(nextCount === depth.U, nextCount, nextCount + 1.U),
                Mux(pop, nextCount - 1.U, nextCount))
        }
        top := nextTop
        count := nextCount
    }
    val previousAuipcValid  = RegInit(false.B)
    val previousAuipcNextPc = Reg(UInt(64.W))
    val previousAuipcValue  = Reg(UInt(64.W))
    val previousAuipcRd     = Reg(UInt(5.W))
    val auipc               = Wire(Vec(p.renameWidth, Bool()))
    val auipcValue          = Wire(Vec(p.renameWidth, UInt(64.W)))
    val auipcRd             = Wire(Vec(p.renameWidth, UInt(5.W)))
    val predicts            = Wire(Vec(p.renameWidth, Bool()))
    val targets             = Wire(Vec(p.renameWidth, UInt(64.W)))
    val lanePcs             = Wire(Vec(p.renameWidth, UInt(64.W)))
    val laneBytes           = Wire(Vec(p.renameWidth, UInt(3.W)))
    // A packet spans at most 4 * renameWidth bytes. Keep prefix arithmetic narrow;
    // each lane then needs only one XLEN-wide PC addition.
    val packetOffsetBits = log2Ceil(4 * p.renameWidth + 1)
    val laneOffsets      = Wire(Vec(p.renameWidth, UInt(packetOffsetBits.W)))
    val acceptedOffsets  = Wire(Vec(p.renameWidth + 1, UInt(packetOffsetBits.W)))
    acceptedOffsets(0) := 0.U(packetOffsetBits.W)
    for (lane <- 0 until p.renameWidth) {
        val decode = Module(new IntegerDecode(p.machineSystem, p.atomicMemory))
        val rawInstruction = io.instructions(lane).bits
        val compressed = p.compressedInstructions.B && rawInstruction(1, 0) =/= 3.U
        val (expanded, compressedLegal) = if (p.compressedInstructions)
            Compressed.expand(rawInstruction(15, 0)) else (rawInstruction, true.B)
        laneOffsets(lane) := (if (lane == 0) 0.U(packetOffsetBits.W)
            else laneOffsets(lane - 1) + laneBytes(lane - 1))
        lanePcs(lane) := pc + laneOffsets(lane)
        laneBytes(lane) := Mux(compressed, 2.U, 4.U)
        val lanePc = lanePcs(lane)
        val pmp = Module(new PmpChecker(p.pmpEntries))
        pmp.io.state     := (if (p.machineSystem) backend.io.pmpState.get else 0.U.asTypeOf(new PmpState))
        pmp.io.address   := lanePc
        pmp.io.size      := 2.U
        pmp.io.privilege := (if (p.machineSystem) backend.io.fetchPrivilege.get else 3.U)
        pmp.io.access    := PmpAccess.execute
        val virtualizedFetch = if (p.virtualMemoryLevels > 0)
            backend.io.vmState.get.satp(63, 60) =/= 0.U && backend.io.fetchPrivilege.get =/= 3.U
        else false.B
        val fetchFault = io.instructionFaults(lane) || io.instructionPageFaults(lane) ||
            (pmp.io.denied && !virtualizedFetch)
        decode.io.pc          := lanePc
        decode.io.instruction := Mux(compressed, Mux(compressedLegal, expanded, 0.U), rawInstruction)
        predictor.io.pc(lane) := lanePc
        indirectPredictor.foreach(_.io.pc(lane) := lanePc)
        val conditional = decode.io.decoded.controlFlow >= ControlFlow.beq &&
            decode.io.decoded.controlFlow <= ControlFlow.bgeu
        val direct = decode.io.decoded.controlFlow === ControlFlow.jal
        auipcRd(lane) := decode.io.decoded.rename.rd
        auipc(lane)   := io.instructions(lane).valid && !fetchFault && decode.io.legal &&
            decode.io.instruction(6, 0) === "h17".U && auipcRd(lane) =/= 0.U
        auipcValue(lane) := lanePc + decode.io.decoded.immediate
        val previousValid = if (lane == 0) previousAuipcValid && previousAuipcNextPc === lanePc else auipc(lane - 1)
        val previousRd    = if (lane == 0) previousAuipcRd else auipcRd(lane - 1)
        val previousValue = if (lane == 0) previousAuipcValue else auipcValue(lane - 1)
        val knownIndirect = decode.io.decoded.controlFlow === ControlFlow.jalr && previousValid &&
            previousRd === decode.io.decoded.rename.rs1
        val linkSource = decode.io.decoded.rename.rs1 === 1.U || decode.io.decoded.rename.rs1 === 5.U
        val returnPredict = p.compressedInstructions.B && returnAvailable &&
            decode.io.decoded.controlFlow === ControlFlow.jalr &&
            decode.io.decoded.rename.rd === 0.U && linkSource && decode.io.decoded.immediate === 0.U
        val indirectHit = indirectPredictor.map(_.io.hit(lane)).getOrElse(false.B)
        val indirectTarget = indirectPredictor.map(_.io.target(lane)).getOrElse(0.U(64.W))
        val indirectPredict = decode.io.decoded.controlFlow === ControlFlow.jalr &&
            !knownIndirect && !returnPredict && indirectHit
        val indirectSum = previousValue + decode.io.decoded.immediate
        targets(lane)  := Mux(knownIndirect, Cat(indirectSum(63, 1), 0.U(1.W)),
            Mux(returnPredict, Cat(returnTop(63, 1), 0.U(1.W)),
                Mux(indirectPredict, indirectTarget, lanePc + decode.io.decoded.immediate)))
        predicts(lane) := io.instructions(lane).valid && !fetchFault &&
            (direct || knownIndirect || returnPredict || indirectPredict ||
                (conditional && predictor.io.taken(lane))) &&
            (if (p.compressedInstructions) !targets(lane)(0) else targets(lane)(1, 0) === 0.U) &&
            targets(lane) =/= lanePc + laneBytes(lane)
        val earlierPrediction = (0 until lane).map(predicts(_)).foldLeft(false.B)(_ || _)
        val faultRequest = WireDefault(0.U.asTypeOf(new IntegerRequest))
        faultRequest.rename.pc := lanePc
        faultRequest.rename.instruction := rawInstruction
        faultRequest.operation := 15.U
        faultRequest.fetchFault := true.B
        faultRequest.fetchPageFault := io.instructionPageFaults(lane)
        faultRequest.fetchTval := io.instructionFaultAddresses.map(_(lane)).getOrElse(lanePc)
        backend.io.allocate(lane).valid := io.instructions(lane).valid && !io.exception.valid && !earlierPrediction
        backend.io.allocate(lane).bits  := Mux(fetchFault, faultRequest, decode.io.decoded)
        backend.io.allocate(lane).bits.rename.instruction := rawInstruction
        backend.io.allocate(lane).bits.predictedNextPc.valid :=
            conditional || direct || knownIndirect || returnPredict || indirectPredict
        backend.io.allocate(lane).bits.predictedNextPc.bits  := Mux(predicts(lane), targets(lane),
            lanePc + laneBytes(lane))
        io.accepted(lane)                                    := backend.io.renamed(lane).valid
        acceptedOffsets(lane + 1) := acceptedOffsets(lane) +
            Mux(io.accepted(lane), laneBytes(lane), 0.U(3.W))
        when(io.accepted(lane)) {
            previousAuipcValid  := auipc(lane)
            previousAuipcNextPc := lanePc + laneBytes(lane)
            previousAuipcValue  := auipcValue(lane)
            previousAuipcRd     := auipcRd(lane)
        }
    }
    when(io.redirect.valid) { previousAuipcValid := false.B }
    val acceptedPrediction = (0 until p.renameWidth).map(i => io.accepted(i) && predicts(i))
    val predictedPc        = Mux(
        acceptedPrediction.reduce(_ || _),
        PriorityMux(acceptedPrediction.zip(targets)),
        pc + acceptedOffsets(p.renameWidth)
    )
    pc := Mux(io.redirect.valid, io.redirect.bits.target, predictedPc)
}
