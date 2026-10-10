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
  * With registeredFetchPacket, fetchPc is instead an independent predicted supply cursor;
  * accepted still reports actual rename admissions, not consumption of the current external
  * supply. A two-packet reservoir separates raw fetch from decode and joins partial packets.
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
        // ROM-device scheduling aid for the single-step GSIM interface; unused
        // by hardware integrations and not an architectural correctness oracle.
        val nextFetchPc                 = if (p.registeredFetchPacket) Some(Output(UInt(64.W))) else None
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
        val loadPrecheck = if (p.virtualRamLoadPrecheck) Some(new VirtualLoadPrecheckPort) else None
        val externalPrefetchBusy = if (p.dataNextLinePrefetch) Some(Input(Bool())) else None
        val posted = p.postedProofConfig.map(c => new PostedStoreCpuPort(c))
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
    io.loadPrecheck.foreach(_ <> backend.io.loadPrecheck.get)
    io.memory <> backend.io.memory
    io.posted.foreach(_ <> backend.io.posted.get)
    if (p.dataNextLinePrefetch) backend.io.externalPrefetchBusy.get := io.externalPrefetchBusy.get
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
    // Keep the architectural admission PC separate from the speculative supply
    // cursor. In particular an interrupt with an empty ROB must resume at pc,
    // never at the fetch cursor which can be several instructions ahead.
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
    val fetchPacketFlush = WireDefault(0.U.asTypeOf(Valid(UInt(64.W))))
    val fetchPacketNext = WireDefault(0.U.asTypeOf(Valid(UInt(64.W))))
    val fetchPacketTraining = WireDefault(0.U.asTypeOf(Vec(p.renameWidth, Valid(new RawFetchSuccessor))))
    val fetchPacket = if (p.registeredFetchPacket) {
        val packet = Module(new RegisteredFetchPacket(p.renameWidth, p.compressedInstructions, resetPc,
            p.parallelFetchValidation, p.fetchHintEntries, p.splitFetchCursor, p.bankedFetchHints))
        val permission = if (p.capturedFetchPermission && p.pmpEntries > 0) {
            val checks = Module(new FetchPacketPermission(p.pmpEntries, p.renameWidth,
                p.wordSpanPacketPmp, p.balancedPacketPmp, p.sharedFetchPmpRelations))
            checks.io.base := packet.io.fetchPc
            checks.io.state := backend.io.pmpState.get
            checks.io.privilege := backend.io.fetchPrivilege.get
            checks.io.virtualized := (if (p.virtualMemoryLevels > 0)
                backend.io.vmState.get.satp(63, 60) =/= 0.U && backend.io.fetchPrivilege.get =/= 3.U
                else false.B)
            for (lane <- 0 until p.renameWidth) {
                checks.io.instructionLow(lane) := io.instructions(lane).bits(1, 0)
            }
            Some(checks)
        } else None
        packet.io.pause := io.exception.valid || io.recovering ||
            backend.io.pauseFetch.map(identity).getOrElse(false.B)
        packet.io.consume := io.accepted
        packet.io.flush := fetchPacketFlush
        packet.io.expectedNext := fetchPacketNext
        packet.io.train := fetchPacketTraining
        packet.io.invalidate := io.invalidateFetch
        for (lane <- 0 until p.renameWidth) {
            packet.io.supply(lane).valid := io.instructions(lane).valid
            packet.io.supply(lane).bits.instruction := io.instructions(lane).bits
            packet.io.supply(lane).bits.accessFault := io.instructionFaults(lane) ||
                permission.map(_.io.denied(lane)).getOrElse(false.B)
            packet.io.supply(lane).bits.pageFault := io.instructionPageFaults(lane)
            val suppliedFaultAddress = io.instructionFaultAddresses
                .map(_(lane)).getOrElse(packet.io.fetchPc + (4 * lane).U)
            // The aligner's fault address is meaningful only when it actually
            // reports a fault. A cached/raw PMP-only denial must name this
            // instruction, not the aligner's unused second-half fallback (+2).
            // Real second-half access/page faults retain their precise address.
            packet.io.supply(lane).bits.faultAddress := permission.map { checks =>
                Mux(checks.io.denied(lane) && !io.instructionFaults(lane) && !io.instructionPageFaults(lane),
                    checks.io.addresses(lane), suppliedFaultAddress)
            }.getOrElse(suppliedFaultAddress)
            // The reservoir generates the real PC and raw successor from its
            // registered cursor and raw lengths, independent of decode.
            packet.io.supply(lane).bits.pc := 0.U
            packet.io.supply(lane).bits.nextPc := 0.U
        }
        io.fetchPc := packet.io.fetchPc
        io.nextFetchPc.get := packet.io.nextFetchPc
        Some(packet)
    } else None
    val instructions = Wire(Vec(p.renameWidth, Valid(UInt(32.W))))
    val instructionFaults = Wire(Vec(p.renameWidth, Bool()))
    val instructionPageFaults = Wire(Vec(p.renameWidth, Bool()))
    val instructionFaultAddresses = Wire(Vec(p.renameWidth, UInt(64.W)))
    for (lane <- 0 until p.renameWidth) {
        val present = fetchPacket.map(_.io.instructions(lane).valid).getOrElse(io.instructions(lane).valid)
        instructions(lane).valid := present
        instructions(lane).bits := fetchPacket.map(_.io.instructions(lane).bits.instruction)
            .getOrElse(io.instructions(lane).bits)
        instructionFaults(lane) := fetchPacket.map(_.io.instructions(lane).bits.accessFault)
            .getOrElse(io.instructionFaults(lane))
        instructionPageFaults(lane) := fetchPacket.map(_.io.instructions(lane).bits.pageFault)
            .getOrElse(io.instructionPageFaults(lane))
        instructionFaultAddresses(lane) := fetchPacket.map(_.io.instructions(lane).bits.faultAddress)
            .getOrElse(io.instructionFaultAddresses.map(_(lane)).getOrElse(0.U))
    }
    val predictor = Module(new BranchPredictor(p))
    val indirectPredictor = if (p.indirectTargetEntries > 0)
        Some(Module(new IndirectTargetPredictor(p))) else None
    val predictionTraining = Module(new CommitPredictionTraining(p))
    for (lane <- 0 until p.commitWidth) {
        val commit = io.commit(lane)
        predictionTraining.io.committed(lane).valid := commit.valid
        predictionTraining.io.committed(lane).bits.pc := commit.bits.pc
        predictionTraining.io.committed(lane).bits.nextPc := commit.bits.nextPc
        predictionTraining.io.committed(lane).bits.instruction := commit.bits.instruction
        predictor.io.train(lane) := predictionTraining.io.branch(lane)
        indirectPredictor.foreach(_.io.train(lane) := predictionTraining.io.indirect(lane))
    }
    val returnTop = WireDefault(0.U(64.W))
    val returnAvailable = WireDefault(false.B)
    if (p.compressedInstructions) {
        val returnStack = Module(new RetirementReturnStack(p.returnStackEntries, p.commitWidth,
            p.pcDerivedReturnLinks, p.parallelReturnStackControl))
        returnAvailable := returnStack.io.available
        returnTop := returnStack.io.target
        for (lane <- 0 until p.commitWidth) {
            val commit = io.commit(lane)
            returnStack.io.commit(lane).valid := commit.valid
            returnStack.io.commit(lane).bits.pc := commit.bits.pc
            returnStack.io.commit(lane).bits.instruction := commit.bits.instruction
            returnStack.io.commit(lane).bits.rd := commit.bits.rd
            returnStack.io.commit(lane).bits.writesRd := commit.bits.writesRd
            returnStack.io.commit(lane).bits.data := commit.bits.data
        }
    }
    val previousAuipcValid  = RegInit(false.B)
    val previousAuipcNextPc = Reg(UInt(64.W))
    val previousAuipcValue  = Reg(UInt(64.W))
    val previousAuipcRd     = Reg(UInt(5.W))
    val auipc               = Wire(Vec(p.renameWidth, Bool()))
    val auipcValue          = Wire(Vec(p.renameWidth, UInt(64.W)))
    val auipcRd             = Wire(Vec(p.renameWidth, UInt(5.W)))
    val predictionImmediates = Wire(Vec(p.renameWidth, UInt(64.W)))
    val predicts            = Wire(Vec(p.renameWidth, Bool()))
    val targets             = Wire(Vec(p.renameWidth, UInt(64.W)))
    val lanePcs             = Wire(Vec(p.renameWidth, UInt(64.W)))
    val laneBytes           = Wire(Vec(p.renameWidth, UInt(3.W)))
    val rawFetchFaults = if (p.tentativeRenameSources) Some(Wire(Vec(p.renameWidth, Bool()))) else None
    backend.io.fetchFaultMask.foreach(_ := rawFetchFaults.get.asUInt)
    // A packet spans at most 4 * renameWidth bytes. Keep prefix arithmetic narrow;
    // each lane then needs only one XLEN-wide PC addition.
    val packetOffsetBits = log2Ceil(4 * p.renameWidth + 1)
    val laneOffsets      = Wire(Vec(p.renameWidth, UInt(packetOffsetBits.W)))
    val acceptedOffsets  = Wire(Vec(p.renameWidth + 1, UInt(packetOffsetBits.W)))
    // PC additions run in parallel with fetch/decode. Late instruction length and
    // rename acceptance only select an already computed PC, instead of launching
    // another 64-bit carry chain at the end of the PC feedback path.
    val packetPcs = (0 to 2 * p.renameWidth).map(i => pc + (2 * i).U)
    def packetPc(offset: UInt): UInt = MuxLookup(offset, pc)(
        packetPcs.zipWithIndex.map { case (target, i) => (2 * i).U -> target })
    acceptedOffsets(0) := 0.U(packetOffsetBits.W)
    val packetPmp = if (p.parallelPacketPmp && p.pmpEntries > 0 && !p.capturedFetchPermission) {
        val checks = Module(new PacketFetchPmp(p.pmpEntries, p.renameWidth, p.wordSpanPacketPmp,
            p.balancedPacketPmp, p.sharedFetchPmpRelations))
        checks.io.base := pc
        checks.io.state := backend.io.pmpState.get
        checks.io.privilege := backend.io.fetchPrivilege.get
        Some(checks)
    } else None
    for (lane <- 0 until p.renameWidth) {
        val decode = Module(new IntegerDecode(p.machineSystem, p.atomicMemory, p.parallelDecodeLegality,
            p.parallelBitLegality, p.fpEnabled, p.fpConfig))
        val rawInstruction = instructions(lane).bits
        val compressed = p.compressedInstructions.B && rawInstruction(1, 0) =/= 3.U
        val (expanded, compressedLegal) = if (p.compressedInstructions)
            Compressed.expand(rawInstruction(15, 0),
                floatingDouble = p.fpEnabled && p.fpConfig.d && p.fpConfig.memory) else (rawInstruction, true.B)
        laneOffsets(lane) := (if (lane == 0) 0.U(packetOffsetBits.W)
            else laneOffsets(lane - 1) + laneBytes(lane - 1))
        lanePcs(lane) := fetchPacket.map(_.io.instructions(lane).bits.pc)
            .getOrElse(packetPc(laneOffsets(lane)))
        laneBytes(lane) := Mux(compressed, 2.U, 4.U)
        // Raw packets may join across a predicted jump. They retain real PCs;
        // decode admits only a sequential prefix, then takes the target under
        // the following cycle's architectural admission PC.
        fetchPacket.foreach { packet =>
            instructions(lane).valid := packet.io.instructions(lane).valid &&
                lanePcs(lane) === packetPc(laneOffsets(lane)) &&
                (if (lane == 0) true.B else instructions(lane - 1).valid)
        }
        val lanePc = lanePcs(lane)
        val successorPc = packetPc(laneOffsets(lane) + laneBytes(lane))
        val pmpDenied = if (p.capturedFetchPermission) false.B else packetPmp.map { checks =>
            MuxLookup(laneOffsets(lane), checks.io.denied(0))(
                checks.io.denied.zipWithIndex.map { case (denied, offset) => (2 * offset).U -> denied })
        }.getOrElse {
            val pmp = Module(new PmpChecker(p.pmpEntries))
            pmp.io.state := (if (p.machineSystem) backend.io.pmpState.get else 0.U.asTypeOf(new PmpState))
            pmp.io.address := lanePc
            pmp.io.size := 2.U
            pmp.io.privilege := (if (p.machineSystem) backend.io.fetchPrivilege.get else 3.U)
            pmp.io.access := PmpAccess.execute
            pmp.io.denied
        }
        val virtualizedFetch = if (p.virtualMemoryLevels > 0)
            backend.io.vmState.get.satp(63, 60) =/= 0.U && backend.io.fetchPrivilege.get =/= 3.U
        else false.B
        val fetchFault = instructionFaults(lane) || instructionPageFaults(lane) ||
            (pmpDenied && !virtualizedFetch)
        rawFetchFaults.foreach(faults => faults(lane) := fetchFault)
        decode.io.pc          := lanePc
        decode.io.instruction := Mux(compressed, Mux(compressedLegal, expanded, 0.U), rawInstruction)
        predictor.io.pc(lane) := lanePc
        indirectPredictor.foreach(_.io.pc(lane) := lanePc)
        val predecode = if (p.parallelFrontendControl) {
            val control = Module(new FrontendControlDecode)
            control.io.instruction := decode.io.instruction
            Some(control)
        } else None
        val conditional = predecode.map(_.io.conditional).getOrElse(
            decode.io.decoded.controlFlow >= ControlFlow.beq && decode.io.decoded.controlFlow <= ControlFlow.bgeu)
        val direct = predecode.map(_.io.direct).getOrElse(decode.io.decoded.controlFlow === ControlFlow.jal)
        val indirect = predecode.map(_.io.indirect).getOrElse(decode.io.decoded.controlFlow === ControlFlow.jalr)
        val predictionRd = predecode.map(_.io.rd).getOrElse(decode.io.decoded.rename.rd)
        val predictionRs1 = predecode.map(_.io.rs1).getOrElse(decode.io.decoded.rename.rs1)
        val predictionImmediate = predecode.map(_.io.immediate).getOrElse(decode.io.decoded.immediate)
        predictionImmediates(lane) := predictionImmediate
        auipcRd(lane) := predictionRd
        // An accepted later lane implies the earlier instruction was valid. Its
        // AUIPC/target payload need not wait for invalidate/valid authorization.
        // State updates still occur only under io.accepted, as before.
        auipc(lane)   := (if (p.stablePredictionMetadata) true.B else instructions(lane).valid) &&
            !fetchFault && predecode.map(_.io.auipc).getOrElse(
                decode.io.legal && decode.io.instruction(6, 0) === "h17".U) && auipcRd(lane) =/= 0.U
        auipcValue(lane) := lanePc + predictionImmediate
        val previousValid = if (lane == 0) previousAuipcValid && previousAuipcNextPc === lanePc else auipc(lane - 1)
        val previousRd    = if (lane == 0) previousAuipcRd else auipcRd(lane - 1)
        val previousValue = if (lane == 0) previousAuipcValue else auipcValue(lane - 1)
        val knownIndirect = indirect && previousValid && previousRd === predictionRs1
        val linkSource = predictionRs1 === 1.U || predictionRs1 === 5.U
        val returnPredict = p.compressedInstructions.B && returnAvailable &&
            indirect && predictionRd === 0.U && linkSource && predictionImmediate === 0.U
        val indirectHit = indirectPredictor.map(_.io.hit(lane)).getOrElse(false.B)
        val indirectTarget = indirectPredictor.map(_.io.target(lane)).getOrElse(0.U(64.W))
        val indirectPredict = indirect &&
            !knownIndirect && !returnPredict && indirectHit
        val indirectSum = previousValue + predictionImmediate
        val knownTarget = Cat(indirectSum(63, 1), 0.U(1.W))
        val returnTarget = Cat(returnTop(63, 1), 0.U(1.W))
        targets(lane)  := Mux(knownIndirect, knownTarget,
            Mux(returnPredict, returnTarget,
                Mux(indirectPredict, indirectTarget, lanePc + predictionImmediate)))
        val fullTargetAligned = if (p.compressedInstructions) !targets(lane)(0) else targets(lane)(1, 0) === 0.U
        val fullTargetDifferent = targets(lane) =/= successorPc
        val relativeGuard = if (p.parallelPredictionQualification) {
            val guard = Module(new DirectPredictionQualification)
            guard.io.pcLow := lanePc(1, 0)
            guard.io.immediate := predictionImmediate
            guard.io.shortInstruction := compressed
            Some(guard)
        } else None
        val (relativeAligned, relativeDifferent) = relativeGuard.map { guard =>
            val pcRelative = conditional || direct
            (Mux(pcRelative, if (p.compressedInstructions) guard.io.aligned16 else guard.io.aligned32,
                fullTargetAligned), Mux(pcRelative, guard.io.differentSuccessor, fullTargetDifferent))
        }.getOrElse((fullTargetAligned, fullTargetDifferent))
        val auipcGuard = if (p.parallelAuipcQualification && lane > 0) {
            val guard = Module(new AuipcPredictionQualification)
            guard.io.auipcPcLow := lanePcs(lane - 1)(1, 0)
            guard.io.upperImmediate := predictionImmediates(lane - 1)(31, 0)
            guard.io.indirectImmediate := predictionImmediate(11, 0)
            guard.io.priorShort := laneBytes(lane - 1) === 2.U
            guard.io.shortInstruction := compressed
            Some(guard)
        } else None
        val (predictionAligned, predictionDifferent) = auipcGuard.map { guard =>
            (Mux(knownIndirect, if (p.compressedInstructions) guard.io.aligned16 else guard.io.aligned32,
                relativeAligned), Mux(knownIndirect, guard.io.differentSuccessor, relativeDifferent))
        }.getOrElse((relativeAligned, relativeDifferent))
        val sourceQualified = if (p.parallelPredictionSources) {
            val source = Module(new PredictionSourceQualification)
            val knownAligned = auipcGuard.map(guard =>
                if (p.compressedInstructions) guard.io.aligned16 else guard.io.aligned32)
                .getOrElse(if (p.compressedInstructions) !knownTarget(0) else knownTarget(1, 0) === 0.U)
            val knownDifferent = auipcGuard.map(_.io.differentSuccessor).getOrElse(knownTarget =/= successorPc)
            // Compare the RAS/table targets in parallel with opcode expansion.
            // Source priority remains known-indirect > return > table > relative.
            source.io.present := VecInit(Seq(knownIndirect, returnPredict, indirectPredict,
                direct || (conditional && predictor.io.taken(lane)))).asUInt
            source.io.aligned := VecInit(Seq(knownAligned,
                if (p.compressedInstructions) !returnTarget(0) else returnTarget(1, 0) === 0.U,
                if (p.compressedInstructions) !indirectTarget(0) else indirectTarget(1, 0) === 0.U,
                if (p.compressedInstructions) relativeGuard.get.io.aligned16 else relativeGuard.get.io.aligned32)).asUInt
            source.io.different := VecInit(Seq(knownDifferent, returnTarget =/= successorPc,
                indirectTarget =/= successorPc, relativeGuard.get.io.differentSuccessor)).asUInt
            source.io.predicts
        } else
            (direct || knownIndirect || returnPredict || indirectPredict ||
                (conditional && predictor.io.taken(lane))) &&
            predictionAligned && predictionDifferent
        predicts(lane) := (if (p.stablePredictionMetadata) true.B else instructions(lane).valid) &&
            !fetchFault && sourceQualified
        fetchPacket.foreach(_.io.validation.foreach { validation =>
            validation(lane).sequentialPc := successorPc
            validation(lane).predictedPc := targets(lane)
            validation(lane).predicts := predicts(lane)
        })
        val earlierPrediction = (0 until lane).map(i => instructions(i).valid && predicts(i))
            .foldLeft(false.B)(_ || _)
        val faultRequest = WireDefault(0.U.asTypeOf(new IntegerRequest))
        faultRequest.rename.pc := lanePc
        faultRequest.rename.instruction := rawInstruction
        faultRequest.operation := 15.U
        faultRequest.fetchFault := true.B
        faultRequest.fetchPageFault := instructionPageFaults(lane)
        faultRequest.fetchTval := (if (p.compressedInstructions) instructionFaultAddresses(lane) else lanePc)
        backend.io.allocate(lane).valid := instructions(lane).valid && !io.exception.valid && !earlierPrediction
        backend.io.allocate(lane).bits  := Mux(fetchFault, faultRequest, decode.io.decoded)
        backend.io.rawRequests.foreach { raw =>
            raw(lane) := decode.io.decoded.rename
            raw(lane).instruction := rawInstruction
        }
        backend.io.rawDestinations.foreach(_(lane) := decode.io.instruction(11, 7))
        backend.io.allocate(lane).bits.rename.instruction := rawInstruction
        backend.io.allocate(lane).bits.predictedNextPc.valid :=
            conditional || direct || knownIndirect || returnPredict || indirectPredict
        backend.io.allocate(lane).bits.predictedNextPc.bits  := Mux(predicts(lane), targets(lane),
            successorPc)
        io.accepted(lane)                                    := backend.io.renamed(lane).valid
        fetchPacketTraining(lane).valid := io.accepted(lane) && !fetchFault &&
            (conditional || direct || indirect)
        fetchPacketTraining(lane).bits.pc := lanePc
        fetchPacketTraining(lane).bits.instruction := rawInstruction
        fetchPacketTraining(lane).bits.nextPc := Mux(predicts(lane), targets(lane), successorPc)
        acceptedOffsets(lane + 1) := acceptedOffsets(lane) +
            Mux(io.accepted(lane), laneBytes(lane), 0.U(3.W))
        when(io.accepted(lane)) {
            previousAuipcValid  := auipc(lane)
            previousAuipcNextPc := successorPc
            previousAuipcValue  := auipcValue(lane)
            previousAuipcRd     := auipcRd(lane)
        }
    }
    when(io.redirect.valid) { previousAuipcValid := false.B }
    val acceptedPrediction = (0 until p.renameWidth).map(i => io.accepted(i) && predicts(i))
    val predictedPc        = Mux(
        acceptedPrediction.reduce(_ || _),
        PriorityMux(acceptedPrediction.zip(targets)),
        packetPc(acceptedOffsets(p.renameWidth))
    )
    pc := Mux(io.redirect.valid, io.redirect.bits.target, predictedPc)
    // Every accepted packet validates the raw path's first successor. Correct
    // early predictions preserve queued target instructions; changed BHT/RAS/
    // indirect predictions cancel the stale raw path precisely. Full recovery
    // and context invalidation retain unconditional cancellation priority.
    fetchPacketNext.valid := io.accepted.reduce(_ || _)
    fetchPacketNext.bits := predictedPc
    fetchPacketFlush.valid := io.redirect.valid || io.invalidateFetch
    fetchPacketFlush.bits := Mux(io.redirect.valid, io.redirect.bits.target, predictedPc)
}
