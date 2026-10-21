package soc.core.inorder

import chisel3._
import chisel3.util._

/** Orbital-I1 named compact5 / balanced7 / fpga8 profiles. Single issue, no ROB/rename.
  * Deeper profiles register EX addresses before lane preparation and raw memory returns before WB.
  * fpga8 additionally captures/snoops the synchronous RF response in an explicit RF stage.
  * Loads forward from registered WB, or registered CMP in the timing-cut profile.
  * Never route raw responses/extension through the EX carry logic.
  * An older CMP fault stops younger irreversible memory effects before it reaches architectural WB.
  */
class FiveStageCore(val p: FiveStageConfig = FiveStageConfig(), externalQuiesce: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val quiesceRequest = if (externalQuiesce) Some(Input(Bool())) else None
        val architecturalStopped = if (externalQuiesce) Some(Output(Bool())) else None
        val instructionRequest = Decoupled(UInt(p.xlen.W))
        val instructionResponse = Flipped(Decoupled(new FiveStageFetchResponse))
        val dataRequest = Decoupled(new FiveStageDataRequest(p))
        val dataResponse = Flipped(Decoupled(new FiveStageDataResponse(p)))
        val dataCandidates = if (p.fpgaTimingCuts && p.fastDataTranslation && p.preparedTranslationProofs)
            Some(Output(Vec(2, new FiveStageDataRequest(p)))) else None
        val dataCandidateEarly = dataCandidates.map(_ => Output(Bool()))
        val dataReadAhead = if (p.dataReplyHandoff) Some(Output(Bool())) else None
        val aia = if (p.withAia) Some(new I1AiaCsrPort) else None
        val fenceIFlush = if (p.externalFenceICompletion) Some(Output(Bool())) else None
        val fenceIFlushReady = if (p.externalFenceICompletion) Some(Input(Bool())) else None
        val fenceIFetchDrained = if (p.externalFenceICompletion) Some(Output(Bool())) else None
        val retire = Valid(new FiveStageRetire(p))
        val time = Input(UInt(64.W))
        val externalIrq = Input(Bool())
        val timerIrq = Input(Bool())
        val softwareIrq = Input(Bool())
        val supervisorExternalIrq = if (p.withSupervisor) Some(Input(Bool())) else None
        val translation = Output(new FiveStageTranslationContext(p))
        val pmp = Output(Vec(p.pmpEntries, new FiveStagePmpEntry(p)))
        val invalidateTranslation = Output(Bool())
        val invalidateInstructionCache = Output(Bool())
        val clearReservation = Output(Bool())
        val trapTaken = Output(Bool())
        val trapPc = Output(UInt(p.xlen.W))
        val trapCause = Output(UInt(p.xlen.W))
        val stageValid = Output(UInt(p.pipeline.size.W))
        val cycles = Output(UInt(64.W))
        val instructions = Output(UInt(64.W))
        val stallLoadUse = Output(Bool())
        val stallMemory = Output(Bool())
        val stallMulDiv = Output(Bool())
        val branchMispredict = Output(Bool())
        val stallFetch = Output(Bool())
        val stallStoreAck = Output(Bool())
        val dataRequestAccepted = Output(Bool())
        val dataRequestOffered = Output(Bool())
    })
    // Optional four-phase architectural stop, NOT cache/Home/DDR or clock-gate acknowledgement.
    // The requester must hold request through stopped, then deassert to resume.
    private val quiesceRequest = io.quiesceRequest.getOrElse(false.B)
    private val quiescePrevious = if (externalQuiesce) RegNext(quiesceRequest, false.B) else false.B
    private val quiesceBlocking = quiesceRequest || quiescePrevious
    private val quiesceRelease = quiescePrevious && !quiesceRequest
    private val ifValid = RegInit(false.B)
    private val idValid = RegInit(false.B)
    private val exValid = RegInit(false.B)
    private val memValid = RegInit(false.B)
    private val wbValid = RegInit(false.B)
    private val wbRecovery = if (p.fpgaTimingCuts) Some(RegInit(false.B)) else None
    private val rrValid = if (p.registerReadStage) RegInit(false.B) else false.B
    private val addrValid = if (p.addressStage) RegInit(false.B) else false.B
    private val cmpValid = if (p.completionStage) RegInit(false.B) else false.B
    private val ifPacket = Reg(new FiveStageInstruction(p))
    private val idPacket = Reg(new FiveStageInstruction(p))
    private val idSerial = if (p.fpgaTimingCuts) Some(Reg(Bool())) else None
    private val exPacket = Reg(new FiveStageExecutePacket(p))
    private val memPacket = Reg(new FiveStageCompletion(p))
    private val wbPacket = Reg(new FiveStageCompletion(p))
    private val aiaSent = if (p.withAia) Some(RegInit(false.B)) else None
    private val aiaDone = if (p.withAia) Some(RegInit(false.B)) else None
    private val wbAia = if (p.withAia) wbPacket.control.csr && I1Aia.indirect(wbPacket.control.csrAddress)
        else false.B
    private val wbAiaWait = if (p.withAia) wbValid && wbAia && !wbPacket.fault && !aiaDone.get else false.B
    private val fenceIFetchDrained = WireDefault(true.B)
    private val wbFenceI = if (p.externalFenceICompletion)
        wbValid && !wbPacket.fault && wbPacket.control.fenceI else false.B
    private val wbFenceIWait = if (p.externalFenceICompletion)
        wbFenceI && (!io.fenceIFlushReady.get || !fenceIFetchDrained) else false.B
    private val wbHold = wbAiaWait || wbFenceIWait
    private val wbCommit = if (p.withAia || p.externalFenceICompletion) wbValid && !wbHold else wbValid
    private val rrPacket = if (p.registerReadStage) Reg(new FiveStageExecutePacket(p))
        else WireDefault(0.U.asTypeOf(new FiveStageExecutePacket(p)))
    private val addrPacket = if (p.addressStage) Reg(new FiveStageCompletion(p))
        else WireDefault(0.U.asTypeOf(new FiveStageCompletion(p)))
    private val cmpPacket = if (p.completionStage) Reg(new FiveStageMemoryReturn(p))
        else WireDefault(0.U.asTypeOf(new FiveStageMemoryReturn(p)))
    private val rrCaptured = if (p.registerReadStage) RegInit(false.B) else false.B
    private val rrLeft = if (p.registerReadStage) Reg(UInt(p.xlen.W)) else 0.U(p.xlen.W)
    private val rrRight = if (p.registerReadStage) Reg(UInt(p.xlen.W)) else 0.U(p.xlen.W)
    private val exLeft = if (p.registerReadStage) Reg(UInt(p.xlen.W)) else 0.U(p.xlen.W)
    private val exRight = if (p.registerReadStage) Reg(UInt(p.xlen.W)) else 0.U(p.xlen.W)
    private val memSent = RegInit(false.B)
    private val mulDivSent = RegInit(false.B)
    private val fpSent = if (p.withF) RegInit(false.B) else false.B
    private val operandHeld = RegInit(false.B)
    private val heldLeft = Reg(UInt(p.xlen.W))
    private val heldRight = Reg(UInt(p.xlen.W))
    private val leftProducer = if (p.fpgaTimingCuts) Some(Reg(UInt(4.W))) else None
    private val rightProducer = if (p.fpgaTimingCuts) Some(Reg(UInt(4.W))) else None
    // Same EX owner/edge. Merge fallback and PC/immediate choice BEFORE the
    // register, rather than producer OR/use-immediate gates before the ALU.
    private val leftAluSelect = if (p.fpgaTimingCuts) Some(Reg(UInt(6.W))) else None
    private val rightAluSelect = if (p.fpgaTimingCuts) Some(Reg(UInt(6.W))) else None
    private val architecturalNextPc = RegInit(p.resetVector.U(p.xlen.W))
    private val rf = Module(new SynchronousRegisterFile(p.xlen, p.registerFileStorage))
    private val decoder = Module(new FiveStageDecode(p))
    private val alu = Module(new FiveStageAlu(p.xlen, p.fpgaTimingCuts))
    private val csr = Module(new FiveStageMachineState(p))
    private val fpr = if (p.withF)
        Some(Module(new SynchronousFloatingRegisterFile(p.flen, p.registerFileStorage))) else None
    private val exFloatingOperands = if (p.withF && p.fpgaTimingCuts)
        Some(Reg(Vec(3, UInt(p.flen.W)))) else None
    private val floatingOperands = exFloatingOperands.map(_.toSeq).getOrElse(
        fpr.toSeq.flatMap(registers => Seq(registers.io.data1, registers.io.data2, registers.io.data3)))
    decoder.io.instruction := idPacket.instruction
    val decodedControl = WireDefault(decoder.io.control)
    if (p.withC) {
        val expand = Module(new FiveStageCompressed(p.xlen, p.withF, p.withD))
        expand.io.instruction := idPacket.instruction(15, 0)
        when(idPacket.compressed) {
            decoder.io.instruction := expand.io.expanded
            decodedControl.legal := decoder.io.control.legal && expand.io.legal
        }
    }
    csr.io.time := io.time
    csr.io.externalIrq := io.externalIrq; csr.io.timerIrq := io.timerIrq; csr.io.softwareIrq := io.softwareIrq
    csr.io.supervisorExternalIrq := io.supervisorExternalIrq.getOrElse(false.B)
    io.translation := csr.io.context; io.pmp := csr.io.pmp
    io.invalidateTranslation := (if (p.fpgaTimingCuts)
        wbCommit && !wbPacket.fault && wbPacket.translationInvalidate.get else csr.io.invalidateTranslation)
    io.cycles := csr.io.cycles; io.instructions := csr.io.instructions
    val stages = Seq(ifValid, idValid) ++ (if (p.registerReadStage) Seq(rrValid) else Nil) ++
        Seq(exValid) ++ (if (p.addressStage) Seq(addrValid) else Nil) ++ Seq(memValid) ++
        (if (p.completionStage) Seq(cmpValid) else Nil) ++ Seq(wbValid)
    io.stageValid := Cat(stages.reverse)
    def needsRecovery(packet: FiveStageCompletion): Bool =
        packet.fault || packet.control.mret || packet.control.sret ||
            packet.control.sfence || packet.control.fenceI || packet.contextBarrier.get
    val wbFlush = if (p.fpgaTimingCuts) wbRecovery.get && !wbHold else wbCommit && (
        wbPacket.fault || wbPacket.control.mret || wbPacket.control.sret ||
        wbPacket.control.sfence || wbPacket.control.fenceI ||
        csr.io.contextBarrier)
    val irqCommit = !quiesceBlocking && csr.io.irqPending && !rrValid && !exValid && !addrValid && !memValid && !cmpValid && !wbValid
    val olderFlush = wbFlush || irqCommit
    // IRQ commit requires every backend owner to be empty. An active stage
    // therefore needs only WB recovery as its older cancellation condition.
    // Keep the actual IRQ trap, frontend redirect and reservation clear below.
    val activeRecovery = if (p.fpgaTimingCuts) wbFlush else olderFlush
    io.clearReservation := olderFlush
    val exRedirect = WireDefault(false.B)
    val redirectPc = Wire(UInt(p.xlen.W))
    val retirementRedirectPc = Wire(UInt(p.xlen.W))
    val flush = olderFlush || exRedirect
    val backendFlush = activeRecovery || exRedirect

    // WB is the only architectural side-effect point. The retire interface has no backpressure.
    io.retire.valid := wbCommit
    io.retire.bits.pc := wbPacket.instruction.pc
    io.retire.bits.instruction := wbPacket.instruction.instruction
    io.retire.bits.nextPc := wbPacket.nextPc
    io.retire.bits.rd := wbPacket.control.rd
    io.retire.bits.writesRd := wbPacket.control.writesRd && wbPacket.control.rd =/= 0.U && !wbPacket.fault
    io.retire.bits.data := wbPacket.result
    io.retire.bits.trap := wbPacket.fault
    io.retire.bits.cause := wbPacket.cause
    io.retire.bits.tval := wbPacket.tval
    io.retire.bits.floating.foreach { commit =>
        commit := wbPacket.floating.get
        commit.write := wbPacket.floating.get.write && !wbPacket.fault
    }
    rf.io.writeEnable := wbCommit && !wbPacket.fault && wbPacket.control.writesRd
    rf.io.rd := wbPacket.control.rd; rf.io.writeData := wbPacket.result
    fpr.foreach { registers =>
        registers.io.writeEnable := wbCommit && !wbPacket.fault && wbPacket.floating.get.write
        registers.io.rd := wbPacket.control.rd
        registers.io.writeData := wbPacket.floating.get.data(p.flen - 1, 0)
    }
    csr.io.fpRetire := wbCommit && !wbPacket.fault && wbPacket.control.floating
    csr.io.fpFlags := wbPacket.floating.map(_.flags).getOrElse(0.U(5.W))
    csr.io.retire := wbCommit && !wbPacket.fault
    csr.io.write.valid := wbCommit && !wbPacket.fault && wbPacket.csrWrite && !wbAia
    csr.io.write.bits.address := wbPacket.control.csrAddress
    csr.io.write.bits.data := wbPacket.csrData
    csr.io.mret := wbCommit && !wbPacket.fault && wbPacket.control.mret
    csr.io.sret := wbCommit && !wbPacket.fault && wbPacket.control.sret
    csr.io.sfence := wbCommit && !wbPacket.fault && wbPacket.control.sfence
    csr.io.trap.valid := (wbCommit && wbPacket.fault) || irqCommit
    csr.io.trap.bits.pc := Mux(irqCommit, architecturalNextPc, wbPacket.instruction.pc)
    csr.io.trap.bits.cause := Mux(irqCommit, csr.io.irqCause, wbPacket.cause)
    csr.io.trap.bits.tval := Mux(irqCommit, 0.U, wbPacket.tval)
    io.trapTaken := csr.io.trap.valid
    io.trapPc := csr.io.trap.bits.pc
    io.trapCause := csr.io.trap.bits.cause
    io.invalidateInstructionCache := wbCommit && !wbPacket.fault && wbPacket.control.fenceI
    when(wbCommit && !wbPacket.fault) { architecturalNextPc := wbPacket.nextPc }
    // Architectural IRQ resume never needs a speculative branch target.
    // Do not leave its register mux connected to EX recovery and rely on
    // synthesis proving mutually exclusive nested conditions.
    when(olderFlush) {
        // The optional restart path needs an exact architectural selection.
        // Do not use the legacy grouped one-hot helper here: its singleton
        // final group can elide the selector and OR a stale sequential PC.
        architecturalNextPc := (if (externalQuiesce)
            Mux(wbFlush, Mux(wbPacket.fault, csr.io.trapPc,
                Mux(wbPacket.control.mret, csr.io.returnPc,
                    Mux(wbPacket.control.sret, csr.io.supervisorReturnPc, wbPacket.nextPc))), csr.io.trapPc)
            else if (p.fpgaTimingCuts) retirementRedirectPc else redirectPc)
    }
    wbValid := wbHold
    wbRecovery.foreach { recovery => when(!wbHold) { recovery := false.B } }
    if (p.externalFenceICompletion) {
        // The platform owns dirty-data publication and downstream drain/epoch completion.
        // Keep this serial owner until that real completion, then emit the existing single
        // I-cache invalidation/retirement redirect. No guessed timeout or local-ready shortcut.
        io.fenceIFlush.get := wbFenceI
        io.fenceIFetchDrained.get := fenceIFetchDrained
        when(io.fenceIFlush.get) {
            assert(!rrValid && !exValid && !addrValid && !memValid && !cmpValid,
                "FENCE.I maintenance overlaps another backend owner")
        }
    }
    if (p.withAia) {
        val port = io.aia.get
        // Serial admission drained all older instructions before EX. Holding this WB owner
        // blocks IRQ commit and younger serial admission until its response is recorded.
        port.request.valid := wbAiaWait && !aiaSent.get
        port.request.bits.file := Mux(wbPacket.control.csrAddress(9), 0.U, 1.U)
        port.request.bits.selector := Mux(wbPacket.control.csrAddress(9),
            csr.io.aiaSelectors.get(0), csr.io.aiaSelectors.get(1))
        port.request.bits.topei := wbPacket.control.csrAddress(3, 0) === 12.U
        // rs1=x0 suppresses CSRRS/CSRRC writes, including topei claim. A nonzero
        // source register containing zero still conveys architectural write intent.
        port.request.bits.operation := Mux(wbPacket.csrWrite, wbPacket.control.funct3(1, 0), 0.U)
        port.request.bits.data := wbPacket.csrData
        port.response.ready := wbAiaWait && aiaSent.get
        when(port.request.fire) { aiaSent.get := true.B }
        when(port.response.fire) {
            aiaDone.get := true.B
            wbPacket.result := port.response.bits.data
            when(port.response.bits.error) {
                wbPacket.fault := true.B
                wbPacket.cause := 2.U
                wbPacket.tval := wbPacket.instruction.instruction.pad(p.xlen)
                wbRecovery.foreach(_ := true.B)
            }
        }
        when(wbCommit) { aiaSent.get := false.B; aiaDone.get := false.B }
        when(wbValid && wbAia) {
            assert(!rrValid && !exValid && !addrValid && !memValid && !cmpValid,
                "IMSIC WB transaction overlaps another backend owner")
        }
        assert(!port.request.fire || (!olderFlush && !wbPacket.fault && wbPacket.control.serial),
            "IMSIC side effect lacks precise serial WB authority")
        assert(!port.response.valid || (wbValid && wbAia && aiaSent.get && !aiaDone.get),
            "IMSIC response has no committed WB owner")
    }

    // The cut profile captured memoryResult (including access errors) at the
    // MEM/CMP edge. Do not decode the raw response a second time in capacity.
    val completionFault = cmpValid && (if (p.fpgaTimingCuts) cmpPacket.completion.fault
        else cmpPacket.completion.fault || cmpPacket.accessed && cmpPacket.response.error)
    def memoryResult(packet: FiveStageCompletion, response: FiveStageDataResponse, accessed: Bool)
        : FiveStageCompletion = {
        val completed = WireDefault(packet)
        val shifted = response.data >> Cat(packet.address(log2Ceil(p.xlen / 8) - 1, 0), 0.U(3.W))
        def extend(bits: Int): UInt = if (bits == p.xlen) shifted(bits - 1, 0) else
            Cat(Fill(p.xlen - bits, !packet.control.funct3(2) && shifted(bits - 1)), shifted(bits - 1, 0))
        val loaded = MuxLookup(packet.control.funct3(1, 0), shifted)(Seq(
            0.U -> extend(8), 1.U -> extend(16), 2.U -> extend(32)))
        when(accessed) {
            when(packet.control.load || packet.control.atomic) {
                completed.result := Mux(packet.control.atomic && packet.control.atomicOperation === 3.U,
                    response.data, loaded)
            }
            completed.floating.foreach { fp =>
                when(packet.control.floating && packet.control.load) {
                    fp.data := Mux(packet.control.funct3 === 2.U, I1FloatingPointBits.boxSingle(shifted), shifted)
                }
            }
            when(response.error) {
                completed.fault := true.B
                completed.cause := Mux(response.pageFault, Mux(packet.control.store, 15.U, 13.U),
                    Mux(packet.control.store, 7.U, 5.U))
                completed.tval := packet.address
            }
        }
        completed
    }
    if (p.completionStage) {
        when(cmpValid && !activeRecovery) {
            wbPacket := (if (p.fpgaTimingCuts) cmpPacket.completion
                else memoryResult(cmpPacket.completion, cmpPacket.response, cmpPacket.accessed))
            wbValid := true.B; cmpValid := false.B
            // Same WB edge and architectural commit cycle. Only predecode the
            // recovery classification from the already registered CMP owner.
            wbRecovery.foreach(_ := needsRecovery(cmpPacket.completion))
        }
    }

    // MEM owns every accepted request until its response. No response can be posted or discarded.
    val memAccess = memPacket.control.load || memPacket.control.store
    // Classification belongs to the MEM owner, not to the backwards READY
    // chain. One metadata bit, no new payload slot, response prediction or edge.
    val memReplyRequired = if (p.fpgaTimingCuts) RegInit(false.B)
        else memAccess && !memPacket.fault
    val emptyEarlySlot = !memValid ||
        (memValid && !memAccess && !memPacket.fault && !memPacket.control.serial)
    val earlySlotAvailable = WireDefault(emptyEarlySlot)
    // Payload is not qualified by response VALID/error or request READY.
    // A sent memory owner no longer offers its request, so only the next
    // owner's candidate payload may be presented while VALID remains low.
    val earlyPayloadSlot = emptyEarlySlot || (p.overlapDataRetirement.B &&
        memValid && memAccess && memSent && !memPacket.fault && !memPacket.control.serial &&
        (!p.readOnlyDataRetirement.B || !memPacket.control.store))
    val earlyRequest = WireDefault(false.B)
    val readAhead = WireDefault(false.B)
    val addressSent = if (p.dataReplyHandoff) Some(RegInit(false.B)) else None
    io.dataReadAhead.foreach(_ := readAhead)
    val earlyPayload = WireDefault(false.B)
    val earlyBits = WireDefault(0.U.asTypeOf(new FiveStageDataRequest(p)))
    io.dataRequest.valid := (memValid && memReplyRequired && !memSent &&
        !activeRecovery && !completionFault) || earlyRequest || readAhead
    val selectEarlyPayload = if (p.fpgaTimingCuts) earlyPayload else earlyRequest
    io.dataCandidates.foreach { candidates =>
        candidates(0) := 0.U.asTypeOf(new FiveStageDataRequest(p))
        candidates(0).address := memPacket.address
        candidates(0).write := memPacket.control.store
        candidates(0).size := memPacket.control.funct3(1, 0)
        candidates(0).data := memPacket.storeData; candidates(0).mask := memPacket.storeMask
        candidates(0).atomic := memPacket.control.atomic
        candidates(0).atomicOperation := memPacket.control.atomicOperation
        candidates(1) := earlyBits
    }
    io.dataCandidateEarly.foreach(_ := selectEarlyPayload)
    io.dataRequest.bits.address := Mux(selectEarlyPayload, earlyBits.address, memPacket.address)
    io.dataRequest.bits.write := Mux(selectEarlyPayload, earlyBits.write, memPacket.control.store)
    io.dataRequest.bits.size := Mux(selectEarlyPayload, earlyBits.size, memPacket.control.funct3(1, 0))
    io.dataRequest.bits.data := Mux(selectEarlyPayload, earlyBits.data, memPacket.storeData)
    io.dataRequest.bits.mask := Mux(selectEarlyPayload, earlyBits.mask, memPacket.storeMask)
    io.dataRequest.bits.noAllocate := false.B
    io.dataRequest.bits.atomic := Mux(selectEarlyPayload, earlyBits.atomic, memPacket.control.atomic)
    io.dataRequest.bits.atomicOperation := Mux(selectEarlyPayload, earlyBits.atomicOperation,
        memPacket.control.atomicOperation)
    io.dataResponse.ready := memValid && memSent && !activeRecovery
    when(io.dataRequest.fire) { memSent := true.B }
    val memComplete = !memReplyRequired || (memSent && io.dataResponse.valid)
    val memFire = memValid && memComplete && !activeRecovery && !completionFault
    if (p.overlapDataRetirement) {
        // The old response is the translation boundary's registered result,
        // not a raw AXI/cache response. Never issue behind an old error or an
        // atomic/serial owner; no store acknowledgement is predicted/posted.
        earlySlotAvailable := emptyEarlySlot || (memFire && memSent && memAccess &&
            !memPacket.fault && !memPacket.control.serial && !io.dataResponse.bits.error &&
            (!p.readOnlyDataRetirement.B || !memPacket.control.store))
    }
    val offsetBits = log2Ceil(p.xlen / 8)
    when(memFire) {
        memValid := false.B; memSent := false.B
        if (p.completionStage) {
            // Finish extraction before the CMP register; EX sees only the
            // registered value. This removes one load-use bubble without a
            // cache/TL response -> extension -> EX arithmetic timing path.
            cmpPacket.completion := (if (p.fpgaTimingCuts)
                memoryResult(memPacket, io.dataResponse.bits, memAccess && !memPacket.fault) else memPacket)
            cmpPacket.response := io.dataResponse.bits
            cmpPacket.accessed := memAccess && !memPacket.fault; cmpValid := true.B
        } else {
            wbPacket := memoryResult(memPacket, io.dataResponse.bits, memAccess && !memPacket.fault)
            wbValid := true.B
        }
    }

    val memReady = !memValid || memFire
    val addressPrepared = WireDefault(addrPacket)
    if (p.fpgaTimingCuts) {
        // EX already captures branchTaken and branchTarget in this SAME packet.
        // nextPc carries the fall-through/xRET candidate until ADDR. Do not
        // append a fault-qualified XLEN PC mux after EX operand/compare logic.
        // Resolve in the existing ADDR stage: no new edge or redirect latency.
        addressPrepared.nextPc := Mux(addrPacket.branchTaken && !addrPacket.fault,
            addrPacket.branchTarget, addrPacket.nextPc)
    }
    val addressMask = MuxLookup(addrPacket.control.funct3(1, 0), 0.U(3.W))(
        Seq(1.U -> 1.U, 2.U -> 3.U, 3.U -> 7.U))
    val addressFault = (addrPacket.control.load || addrPacket.control.store) &&
        (addrPacket.address(2, 0) & addressMask).orR
    if (p.addressStage) {
        val bytes = MuxLookup(addrPacket.control.funct3(1, 0), 1.U((p.xlen / 8).W))(Seq(
            1.U -> 3.U((p.xlen / 8).W), 2.U -> 15.U((p.xlen / 8).W)
        ) ++ (if (p.xlen == 64) Seq(3.U -> 255.U(8.W)) else Nil))
        addressPrepared.storeData := (addrPacket.storeSource <<
            Cat(addrPacket.address(offsetBits - 1, 0), 0.U(3.W)))(p.xlen - 1, 0)
        addressPrepared.storeMask := (bytes << addrPacket.address(offsetBits - 1, 0))(p.xlen / 8 - 1, 0)
        when(!addrPacket.fault && addressFault) {
            addressPrepared.fault := true.B
            addressPrepared.cause := Mux(addrPacket.control.store, 6.U, 4.U)
            addressPrepared.tval := addrPacket.address
        }
    }
    // Occupancy and local completion are separate from the recovery mask.
    // Do not ripple MEM fire -> ADDR fire -> EX fire -> frontend capacity.
    val backendProgress = !activeRecovery && !completionFault
    val addressRoom = if (p.fpgaTimingCuts) !memValid || memComplete else memReady
    val addressFire = addrValid && addressRoom && backendProgress
    val executeReady = if (p.addressStage) !addrValid || addressFire else memReady
    when(addressFire) {
        if (p.addressStage) {
            memPacket := addressPrepared; memValid := true.B; addrValid := false.B
            memSent := addressSent.getOrElse(false.B) || (earlyRequest && io.dataRequest.fire)
            addressSent.foreach(_ := false.B)
            if (p.fpgaTimingCuts) {
                memReplyRequired := (addressPrepared.control.load || addressPrepared.control.store) &&
                    !addressPrepared.fault
            }
        }
    }

    // EX forwarding is local and bounded to MEM/WB. A stalled EX captures its operands.
    val c = exPacket.control
    def memMatch(address: UInt, used: Bool): Bool = memValid &&
        (p.fpgaTimingCuts.B || !memPacket.fault) &&
        memPacket.control.writesRd && memPacket.control.rd =/= 0.U && used && memPacket.control.rd === address
    def wbMatch(address: UInt, used: Bool): Bool = wbCommit && !wbPacket.fault &&
        wbPacket.control.writesRd && wbPacket.control.rd =/= 0.U && used && wbPacket.control.rd === address
    def addressMatch(address: UInt, used: Bool): Bool = addrValid &&
        (p.fpgaTimingCuts.B || !addressPrepared.fault) &&
        addrPacket.control.writesRd && addrPacket.control.rd =/= 0.U && used && addrPacket.control.rd === address
    def completionMatch(address: UInt, used: Bool): Bool = cmpValid &&
        (p.fpgaTimingCuts.B || !completionFault) &&
        cmpPacket.completion.control.writesRd && cmpPacket.completion.control.rd =/= 0.U &&
        used && cmpPacket.completion.control.rd === address
    val memLeft = memMatch(c.rs1, c.usesRs1)
    val memRight = memMatch(c.rs2, c.usesRs2)
    val addressLeft = addressMatch(c.rs1, c.usesRs1)
    val addressRight = addressMatch(c.rs2, c.usesRs2)
    val completionLeft = completionMatch(c.rs1, c.usesRs1)
    val completionRight = completionMatch(c.rs2, c.usesRs2)
    // A matching faulting producer still OWNS its rd and blocks fallback to
    // an older writer until the precise fault flushes it. Alignment is new
    // ADDR combinational work, but cannot apply to a forwardable non-memory
    // ALU result. Qualify that result only with the registered fault bit.
    val canMemForward = p.memoryBypass.B && !memPacket.control.load && !memPacket.control.atomic &&
        (!p.fpgaTimingCuts.B || !memPacket.fault)
    val canAddressForward = p.memoryBypass.B && !addrPacket.control.load && !addrPacket.control.atomic &&
        (!p.fpgaTimingCuts.B || !addrPacket.fault)
    val canCompletionForward = p.memoryBypass.B && !cmpPacket.completion.control.atomic &&
        (!cmpPacket.completion.control.load || p.fpgaTimingCuts.B) &&
        (!p.fpgaTimingCuts.B || !completionFault)
    // Only the closest matching producer controls dependency/value; an older same-rd must not win.
    val availableOperands = Seq(canAddressForward, canMemForward, canCompletionForward, true.B, true.B, true.B)
    def operandOwners(index: UInt, used: Bool, addressHit: Bool, memoryHit: Bool,
        completionHit: Bool, enabled: Bool): Seq[Bool] =
        I1ExecuteDatapath.operandMasksWhen(enabled, Seq(addressHit, memoryHit, completionHit,
            wbMatch(index, used), operandHeld, true.B))
    val legacyLeftOwners = operandOwners(c.rs1, c.usesRs1, addressLeft, memLeft, completionLeft,
        exPacket.operandEnable.map(_(0)).getOrElse(c.usesRs1 && c.rs1 =/= 0.U))
    val legacyRightOwners = operandOwners(c.rs2, c.usesRs2, addressRight, memRight, completionRight,
        exPacket.operandEnable.map(_(1)).getOrElse(c.usesRs2 && c.rs2 =/= 0.U))
    def retainedOwners(producer: UInt, enabled: Bool): Seq[Bool] =
        (0 until 4).map(i => producer(i)) ++ Seq(
            enabled && !producer.orR && operandHeld, enabled && !producer.orR && !operandHeld)
    val leftOwners = leftProducer.map(mask => retainedOwners(mask,
        exPacket.operandEnable.get(0))).getOrElse(legacyLeftOwners)
    val rightOwners = rightProducer.map(mask => retainedOwners(mask,
        exPacket.operandEnable.get(1))).getOrElse(legacyRightOwners)
    if (p.fpgaTimingCuts) when(exValid && !activeRecovery && !reset.asBool) {
        assert(VecInit(leftOwners).asUInt === VecInit(legacyLeftOwners).asUInt &&
            VecInit(rightOwners).asUInt === VecInit(legacyRightOwners).asUInt,
            "registered EX producer handoff changed nearest-writer ownership")
    }
    def blocked(owners: Seq[Bool]): Bool =
        VecInit(owners.take(3).zip(availableOperands.take(3)).map { case (owner, ready) => owner && !ready })
            .asUInt.orR
    val leftDependency = if (p.fpgaTimingCuts) blocked(leftOwners)
        else Mux(addressLeft, !canAddressForward, Mux(memLeft, !canMemForward, completionLeft && !canCompletionForward))
    val rightDependency = if (p.fpgaTimingCuts) blocked(rightOwners)
        else Mux(addressRight, !canAddressForward, Mux(memRight, !canMemForward, completionRight && !canCompletionForward))
    val dependency = leftDependency || rightDependency
    val baseLeft = if (p.registerReadStage) exLeft else rf.io.data1
    val baseRight = if (p.registerReadStage) exRight else rf.io.data2
    val legacyRs1 = Mux(c.rs1 === 0.U, 0.U, Mux(addressLeft && canAddressForward, addrPacket.result,
        Mux(memLeft && canMemForward, memPacket.result,
            Mux(completionLeft && canCompletionForward, cmpPacket.completion.result,
                Mux(wbMatch(c.rs1, c.usesRs1), wbPacket.result, Mux(operandHeld, heldLeft, baseLeft))))))
    val legacyRs2 = Mux(c.rs2 === 0.U, 0.U, Mux(addressRight && canAddressForward, addrPacket.result,
        Mux(memRight && canMemForward, memPacket.result,
            Mux(completionRight && canCompletionForward, cmpPacket.completion.result,
                Mux(wbMatch(c.rs2, c.usesRs2), wbPacket.result, Mux(operandHeld, heldRight, baseRight))))))
    val leftMasks = I1ExecuteDatapath.admittedMasks(leftOwners, availableOperands)
    val rightMasks = I1ExecuteDatapath.admittedMasks(rightOwners, availableOperands)
    val leftValues = Seq(addrPacket.result, memPacket.result, cmpPacket.completion.result,
        wbPacket.result, heldLeft, baseLeft)
    val rightValues = Seq(addrPacket.result, memPacket.result, cmpPacket.completion.result,
        wbPacket.result, heldRight, baseRight)
    // The closest producer owns the payload even while its value is not ready.
    // Only dependency/admission may consume it. Availability must not sit in
    // the data mux before the ALU carry chain, or select an older same-rd value.
    // The RF->EX edge already zeroes unused/x0 base operands. The producer
    // bits themselves include architectural use/nonzero qualification.
    // Do not put operandEnable -> fallback mux -> XLEN ALU in one cycle.
    def preparedPayloadOwners(producer: UInt): Seq[Bool] =
        (0 until 4).map(i => producer(i)) ++ Seq(!producer.orR)
    // The existing held operands are preloaded at RF->EX. Their payload is
    // therefore the fallback even before the first stall: no operandHeld ->
    // XLEN mux -> ALU chain, and no new bypass/owner/edge.
    val payloadLeftValues = if (p.fpgaTimingCuts) leftValues.take(4) :+ heldLeft else leftValues
    val payloadRightValues = if (p.fpgaTimingCuts) rightValues.take(4) :+ heldRight else rightValues
    val payloadLeftMasks = if (p.fpgaTimingCuts) preparedPayloadOwners(leftProducer.get) else leftMasks
    val payloadRightMasks = if (p.fpgaTimingCuts) preparedPayloadOwners(rightProducer.get) else rightMasks
    val rs1 = if (p.fpgaTimingCuts) I1ExecuteDatapath.operand(payloadLeftMasks, payloadLeftValues) else legacyRs1
    val rs2 = if (p.fpgaTimingCuts) I1ExecuteDatapath.operand(payloadRightMasks, payloadRightValues) else legacyRs2
    when(p.fpgaTimingCuts.B && exValid && !dependency && !reset.asBool) {
        assert(rs1 === I1ExecuteDatapath.operand(leftMasks, leftValues),
            "EX consumed an unavailable left producer payload")
        assert(rs2 === I1ExecuteDatapath.operand(rightMasks, rightValues),
            "EX consumed an unavailable right producer payload")
    }
    alu.io.operation := c.aluOp; alu.io.word := c.word
    alu.io.resultEnable.foreach(_ := exPacket.resultMask.get(4))
    alu.io.left := (if (p.fpgaTimingCuts) I1ExecuteDatapath.operand(
        leftAluSelect.get.asBools, payloadLeftValues :+ exPacket.instruction.pc)
        else Mux(c.usePc, exPacket.instruction.pc, Mux(c.usesRs1, rs1, 0.U)))
    alu.io.right := (if (p.fpgaTimingCuts) I1ExecuteDatapath.operand(
        rightAluSelect.get.asBools, payloadRightValues :+ c.immediate)
        else Mux(c.useImmediate, c.immediate, rs2))
    if (p.fpgaTimingCuts) when(exValid && !dependency && !reset.asBool) {
        assert(alu.io.left === I1ExecuteDatapath.overrideOperand(
            payloadLeftMasks, payloadLeftValues, c.usePc, exPacket.instruction.pc) &&
            alu.io.right === I1ExecuteDatapath.overrideOperand(
                payloadRightMasks, payloadRightValues, c.useImmediate, c.immediate),
            "prepared ALU selection changed the retained closest producer")
    }
    val sequentialPc = if (p.fpgaTimingCuts) Mux(p.withC.B && exPacket.instruction.compressed,
        exPacket.instruction.pc + 2.U, exPacket.instruction.pc + 4.U)
        else exPacket.instruction.pc + Mux(p.withC.B && exPacket.instruction.compressed, 2.U, 4.U)
    def addressSum(left: UInt, right: UInt): UInt =
        if (p.fpgaTimingCuts) I1TimingMath.add(left, right) else left + right
    val target = Mux(c.jumpRegister, addressSum(rs1, c.immediate) &
        ((BigInt(1) << p.xlen) - 2).U(p.xlen.W), addressSum(exPacket.instruction.pc, c.immediate))
    val branchEqual = if (p.fpgaTimingCuts) I1TimingMath.equal(rs1, rs2) else rs1 === rs2
    val branchUnsignedLess = if (p.fpgaTimingCuts) I1TimingMath.less(rs1, rs2) else rs1 < rs2
    val branchSignedLess = Mux(rs1(p.xlen - 1) =/= rs2(p.xlen - 1), rs1(p.xlen - 1), branchUnsignedLess)
    val branchTaken = MuxLookup(c.funct3, false.B)(Seq(
        0.U -> branchEqual, 1.U -> !branchEqual, 4.U -> branchSignedLess,
        5.U -> !branchSignedLess, 6.U -> branchUnsignedLess, 7.U -> !branchUnsignedLess
    ))
    val takeBranch = c.jump || (c.branch && branchTaken)
    val address = addressSum(rs1, c.immediate)
    val alignmentMask = MuxLookup(c.funct3(1, 0), 0.U(p.xlen.W))(
        Seq(1.U -> 1.U(p.xlen.W), 2.U -> 3.U(p.xlen.W), 3.U -> 7.U(p.xlen.W)))
    // Alignment only needs low address bits. Keep it independent of the XLEN carry chain.
    val addressLow = (rs1(2, 0) + c.immediate(2, 0))(2, 0)
    val targetLow = Mux(c.jumpRegister,
        Cat((rs1(1, 0) + c.immediate(1, 0))(1), 0.U(1.W)),
        (exPacket.instruction.pc(1, 0) + c.immediate(1, 0))(1, 0))
    val memoryMisaligned = (!p.addressStage).B && (c.load || c.store) && (addressLow & alignmentMask(2, 0)).orR
    val branchMisaligned = takeBranch && (if (p.withC) targetLow(0) else targetLow.orR)
    csr.io.readAddress := c.csrAddress
    val csrSource = Mux(c.csrImmediate, c.rs1.pad(p.xlen), rs1)
    val csrWrite = c.csr && (c.funct3(1, 0) === 1.U || c.rs1 =/= 0.U)
    val csrIllegal = c.csr && (!csr.io.readLegal || (csrWrite && c.csrAddress(11, 10) === 3.U))
    val fpInstruction = exPacket.expanded.getOrElse(0.U(32.W))
    val fpRounding = Mux(c.funct3 === 7.U, csr.io.fpRounding, c.funct3)
    val fpIllegal = c.floating && (!csr.io.fpEnabled ||
        (c.fpExecute && I1FloatingPointDecode.usesRounding(fpInstruction) && fpRounding > 4.U))
    val csrData = MuxLookup(c.funct3(1, 0), csrSource)(Seq(
        2.U -> (csr.io.readDataForWrite | csrSource), 3.U -> (csr.io.readDataForWrite & ~csrSource)))
    val systemIllegal = (c.mret && !csr.io.mretLegal) || (c.sret && !csr.io.sretLegal) ||
        (c.sfence && !csr.io.sfenceLegal) || (c.wfi && !csr.io.wfiLegal)
    val illegal = !c.legal || csrIllegal || systemIllegal || fpIllegal
    val instructionFault = exPacket.instruction.fetchError || illegal || c.ecall || c.ebreak
    // Numerical opcodes cannot also be CSR/system opcodes. Their legality
    // was captured at the existing ID edge, where serial FP already drains
    // all older state changes. No CSR read-legal tree belongs in EX capacity.
    val numericalFault = exPacket.numericalLegal.map(!_).getOrElse(instructionFault)
    val numericalRounding = exPacket.numericalRounding.getOrElse(fpRounding)
    val exFault = instructionFault ||
        memoryMisaligned || branchMisaligned
    val exCause = Mux(exPacket.instruction.fetchError, Mux(exPacket.instruction.fetchPageFault, 12.U, 1.U),
        Mux(illegal, 2.U, Mux(c.ebreak, 3.U, Mux(c.ecall,
            Mux(csr.io.context.privilege === 0.U, 8.U, Mux(csr.io.context.privilege === 1.U, 9.U, 11.U)),
            Mux(branchMisaligned, 0.U, Mux(c.store, 6.U, 4.U))))))
    // Unsupported >32-bit prefix is rejected from its first parcel. We do not claim uncaptured bits in mtval.
    val illegalValue = Mux(p.withC.B && !exPacket.instruction.compressed &&
        exPacket.instruction.instruction(4, 0) === 31.U, 0.U, exPacket.instruction.instruction.pad(p.xlen))
    val legacyExTval = Mux(exPacket.instruction.fetchError || c.ebreak, exPacket.instruction.pc +
        Mux(exPacket.instruction.fetchError && exPacket.instruction.fetchSecondHalfFault, 2.U, 0.U),
        Mux(illegal, illegalValue, Mux(branchMisaligned, target,
            Mux(memoryMisaligned, address, 0.U))))
    // Fault payload selection is by the registered instruction class, NOT
    // by the resolved branch comparison. Only a fault consumes tval at WB.
    val fetchFaultPc = Mux(exPacket.instruction.fetchError && exPacket.instruction.fetchSecondHalfFault,
        exPacket.instruction.pc + 2.U, exPacket.instruction.pc)
    val classFaultValue = Mux(c.jump || c.branch, target, Mux(c.load || c.store, address, 0.U))
    val exTval = if (p.fpgaTimingCuts) Mux(exPacket.instruction.fetchError || c.ebreak, fetchFaultPc,
        Mux(illegal, illegalValue, Mux(c.ecall, 0.U, classFaultValue))) else legacyExTval
    when(exValid && exFault) { assert(exTval === legacyExTval, "class-selected exception payload mismatch") }
    val mulResult = WireDefault(0.U(p.xlen.W))
    val mulComplete = WireDefault(true.B)
    val fpResult = WireDefault(0.U(64.W))
    val fpFlags = WireDefault(0.U(5.W))
    val fpComplete = WireDefault(true.B)
    // Only M operations wait for the MDU. Late address/branch faults go to WB with their
    // packet; they cannot affect the common EX -> ID -> IF capacity/READY chain.
    val executeRoom = if (p.fpgaTimingCuts) !addrValid || !memValid || memComplete else executeReady
    val executeLocalReady = !dependency &&
        (!c.mulDiv || mulComplete || numericalFault) && (!c.fpExecute || fpComplete || numericalFault)
    val executeAdmission = exValid && executeRoom && !dependency && backendProgress
    val exFire = exValid && executeRoom && executeLocalReady && backendProgress
    val floatingStore = if (p.withF) floatingOperands(1).pad(p.xlen) else 0.U(p.xlen.W)
    val storeSource = Mux(c.floating && c.store, floatingStore, rs2)
    val storeData = (storeSource << Cat(address(offsetBits - 1, 0), 0.U(3.W)))(p.xlen - 1, 0)
    val storeByteMask = MuxLookup(c.funct3(1, 0), 1.U((p.xlen / 8).W))(Seq(
        1.U -> 3.U((p.xlen / 8).W), 2.U -> 15.U((p.xlen / 8).W)
    ) ++ (if (p.xlen == 64) Seq(3.U -> 255.U(8.W)) else Nil))
    val storeMask = (storeByteMask << address(offsetBits - 1, 0))(p.xlen / 8 - 1, 0)
    if (p.earlyMemoryIssue) {
        // Empty/non-memory retirement is always eligible. Optional data
        // retirement overlap additionally requires a real successful reply.
        // EX transfers to MEM regardless of external READY. If stalled, the identical packet
        // continues as the normal MEM offer on the next cycle. No accepted owner is duplicated.
        if (p.addressStage) {
            val ac = addrPacket.control
            val replacementType = !p.readOnlyDataRetirement.B || !memValid || !memAccess || (ac.load && !ac.store)
            earlyRequest := addressFire && !addressSent.getOrElse(false.B) &&
                earlySlotAvailable && (ac.load || ac.store) &&
                !ac.atomic && !addressPrepared.fault && replacementType
            if (p.dataReplyHandoff) {
                // Reuse ADDR, not a new load queue. DT may accept this read
                // ONLY at a real successful old physical response edge, with
                // a live full-page proof and cacheable aligned scalar PA.
                // The old reply remains registered; ADDR later transfers its
                // accepted bit to MEM rather than issuing the load twice.
                readAhead := addrValid && !addressFire && !addressSent.get &&
                    memValid && memSent && memAccess && !memPacket.fault &&
                    !memPacket.control.serial && !memPacket.control.atomic &&
                    ac.load && !ac.store && !ac.atomic && !addressPrepared.fault && backendProgress
                when(readAhead && io.dataRequest.fire) { addressSent.get := true.B }
            }
            // Payload selection has no WB flush/permission/READY dependence.
            // An actual transfer is still qualified by earlyRequest above.
            earlyPayload := addrValid && earlyPayloadSlot && (ac.load || ac.store) && !ac.atomic && replacementType
            earlyBits.address := addrPacket.address; earlyBits.write := ac.store; earlyBits.size := ac.funct3(1, 0)
            earlyBits.data := addressPrepared.storeData; earlyBits.mask := addressPrepared.storeMask
        } else {
            earlyRequest := exFire && earlySlotAvailable && (c.load || c.store) && !c.atomic && !exFault
            earlyBits.address := address; earlyBits.write := c.store; earlyBits.size := c.funct3(1, 0)
            earlyBits.data := storeData; earlyBits.mask := storeMask
        }
    }
    if (p.withM) {
        val mulDiv = Module(new FiveStageMulDiv(p))
        mulDiv.io.kill := activeRecovery || (p.fpgaTimingCuts.B && exRedirect)
        mulDiv.io.request.valid := exValid && c.mulDiv && !numericalFault &&
            !dependency && !mulDivSent && !activeRecovery && !completionFault &&
            !(p.fpgaTimingCuts.B && exRedirect)
        mulDiv.io.request.bits.left := rs1; mulDiv.io.request.bits.right := rs2
        mulDiv.io.request.bits.funct3 := c.funct3; mulDiv.io.request.bits.word := c.word
        mulDiv.io.response.ready := (if (p.fpgaTimingCuts)
            executeAdmission && !exRedirect && c.mulDiv && !numericalFault
            else exFire && c.mulDiv && !instructionFault)
        when(mulDiv.io.request.fire) { mulDivSent := true.B }
        mulResult := mulDiv.io.response.bits
        mulComplete := (if (p.fpgaTimingCuts) mulDiv.io.completed else mulDiv.io.response.valid)
        when(exFire && c.mulDiv && !numericalFault && !backendFlush) {
            assert(mulDiv.io.response.fire, "live MDU advance must consume its real response")
        }
    }
    if (p.withF) {
        val execute = Module(new I1FloatingPointExecute(p, p.floatingConfig))
        execute.io.flush := activeRecovery || (p.fpgaTimingCuts.B && exRedirect)
        execute.io.request.valid := exValid && c.fpExecute && !numericalFault &&
            !dependency && !fpSent && !activeRecovery && !completionFault &&
            !(p.fpgaTimingCuts.B && exRedirect)
        execute.io.request.bits := 0.U.asTypeOf(new I1FloatingPointExecution(p))
        execute.io.request.bits.command.instruction := fpInstruction
        execute.io.request.bits.command.integerSource := rs1
        execute.io.request.bits.rounding := numericalRounding
        for ((operand, index) <- floatingOperands.zipWithIndex) {
            execute.io.request.bits.operands(index) :=
                (if (p.withD) operand else I1FloatingPointBits.boxSingle(operand))
        }
        execute.io.result.ready := (if (p.fpgaTimingCuts)
            executeAdmission && !exRedirect && c.fpExecute && !numericalFault
            else exFire && c.fpExecute && !instructionFault)
        fpResult := execute.io.result.bits.value
        fpFlags := execute.io.result.bits.flags
        fpComplete := (if (p.fpgaTimingCuts) execute.io.completed else execute.io.result.valid)
        when(exFire && c.fpExecute && !numericalFault && !backendFlush) {
            assert(execute.io.result.fire, "live floating advance must consume its real response")
        }
        when(execute.io.request.fire) { fpSent := true.B }
        when(execute.io.result.valid && !activeRecovery && !(p.fpgaTimingCuts.B && exRedirect)) {
            assert(exValid && c.fpExecute && fpSent && !execute.io.result.bits.exception,
                "floating result must belong to the live legal EX owner")
        }
    }
    val exNextPc = Mux(c.mret, csr.io.returnPc, Mux(c.sret, csr.io.supervisorReturnPc,
        Mux(takeBranch && !exFault, target, sequentialPc)))
    // Compare both candidate PCs in parallel before choosing the boolean.
    // Conditional-branch comparison must not feed an XLEN mux and then a
    // second XLEN comparison before frontend kill/admission.
    val predictionMismatch = if (p.fpgaTimingCuts)
        Mux(takeBranch, target =/= exPacket.instruction.predictedNextPc,
            sequentialPc =/= exPacket.instruction.predictedNextPc)
        else exNextPc =/= exPacket.instruction.predictedNextPc
    if (p.fpgaTimingCuts) {
        // Resolve from the EXISTING ADDR packet, after forwarding, branch
        // comparison and next-PC selection have crossed a register edge.
        // The branch itself continues to MEM; flush only younger EX/RF/ID/IF.
        // No ninth stage, extra owner or early architectural side effect.
        val ac = addrPacket.control
        val mismatch = if (p.branchPredictorEntries > 0 || p.withC)
            Mux(addrPacket.branchTaken && !addrPacket.fault,
                !I1TimingMath.equal(addrPacket.branchTarget, addrPacket.instruction.predictedNextPc),
                !I1TimingMath.equal(addrPacket.nextPc, addrPacket.instruction.predictedNextPc)) else addrPacket.branchTaken
        exRedirect := addressFire && !addressPrepared.fault && !ac.mret && !ac.sret &&
            !ac.sfence && !ac.fenceI && mismatch
    } else if (p.branchPredictorEntries > 0) {
        exRedirect := exFire && !exFault && !c.mret && !c.sret && !c.sfence && !c.fenceI &&
            predictionMismatch
    } else if (p.withC) {
        // Without a length predictor, the same EX repair handles compressed sequential boundaries.
        exRedirect := exFire && !exFault && !c.mret && !c.sret && !c.sfence && !c.fenceI &&
            predictionMismatch
    } else {
        // Disabled prediction preserves the physically measured foundation control path.
        exRedirect := exFire && takeBranch && !instructionFault && !branchMisaligned
    }
    io.branchMispredict := exRedirect
    if (p.fpgaTimingCuts) {
        val retire = wbFlush && !wbPacket.fault
        val masks = Seq(!retire, retire && wbPacket.control.mret,
            retire && !wbPacket.control.mret && wbPacket.control.sret,
            retire && !wbPacket.control.mret && !wbPacket.control.sret)
        val values = Seq(csr.io.trapPc, csr.io.returnPc, csr.io.supervisorReturnPc, wbPacket.nextPc)
        retirementRedirectPc := I1ExecuteDatapath.operand(masks, values)
        val branch = addrPacket.branchTaken && !addrPacket.fault
        redirectPc := I1ExecuteDatapath.operand(masks.map(_ && olderFlush) ++
            Seq(!olderFlush && branch, !olderFlush && !branch),
            values ++ Seq(addrPacket.branchTarget, addrPacket.nextPc))
    } else {
        retirementRedirectPc := Mux(wbFlush, Mux(wbPacket.fault, csr.io.trapPc,
            Mux(wbPacket.control.mret, csr.io.returnPc,
                Mux(wbPacket.control.sret, csr.io.supervisorReturnPc, wbPacket.nextPc))), csr.io.trapPc)
        redirectPc := Mux(wbFlush, retirementRedirectPc, Mux(irqCommit, csr.io.trapPc, exNextPc))
    }
    when(exValid && !exFire) { heldLeft := rs1; heldRight := rs2; operandHeld := true.B }
    val executed = WireDefault(0.U.asTypeOf(new FiveStageCompletion(p)))
    executed.instruction := exPacket.instruction; executed.control := c
    executed.result := (if (p.fpgaTimingCuts) I1ExecuteDatapath.resultFromEnabledAlu(exPacket.resultMask.get,
        Seq(fpResult, sequentialPc, csr.io.readData, mulResult), alu.io.result)
        else Mux(c.fpExecute, fpResult, Mux(c.jump, sequentialPc,
            Mux(c.csr, csr.io.readData, Mux(c.mulDiv, mulResult, alu.io.result)))))
    executed.address := address
    executed.storeSource := (if (p.addressStage) storeSource else 0.U)
    executed.storeData := (if (p.addressStage) 0.U else storeData)
    executed.storeMask := (if (p.addressStage) 0.U else storeMask)
    executed.nextPc := (if (p.fpgaTimingCuts)
        Mux(c.mret, csr.io.returnPc, Mux(c.sret, csr.io.supervisorReturnPc, sequentialPc)) else exNextPc)
    executed.branchTaken := takeBranch; executed.branchTarget := target
    executed.fault := exFault; executed.cause := exCause; executed.tval := exTval
    executed.csrWrite := csrWrite
    executed.csrData := (if (p.withAia) Mux(I1Aia.indirect(c.csrAddress), csrSource, csrData) else csrData)
    val changesMap = c.csrAddress === "h180".U || p.pmpEntries.U =/= 0.U &&
        c.csrAddress >= "h3a0".U && c.csrAddress <= "h3bf".U
    executed.contextBarrier.foreach(_ := csrWrite &&
        (changesMap || c.csrAddress === "h300".U || c.csrAddress === "h100".U))
    executed.translationInvalidate.foreach(_ := c.sfence || csrWrite && changesMap)
    executed.floating.foreach { fp =>
        fp.write := c.fpWrites
        fp.data := fpResult
        fp.flags := Mux(c.fpExecute && !numericalFault, fpFlags, 0.U)
    }
    when(exFire) {
        exValid := false.B; mulDivSent := false.B; operandHeld := false.B
        if (p.addressStage) { addrValid := true.B; addrPacket := executed }
        else { memValid := true.B; memSent := earlyRequest && io.dataRequest.fire; memPacket := executed }
        if (p.withF) { fpSent := false.B }
    }

    // Serial operations drain older instructions before reading privileged state, and stop younger ID.
    val olderSerial = (exValid && c.serial) || (addrValid && addrPacket.control.serial) ||
        (memValid && memPacket.control.serial) || (cmpValid && cmpPacket.completion.control.serial) ||
        (wbValid && wbPacket.control.serial)
    val serialDrain = idSerial.getOrElse(decodedControl.serial) &&
        (rrValid || exValid || addrValid || memValid || cmpValid || wbValid)
    idSerial.foreach { serial =>
        when(idValid && !reset.asBool) {
            assert(serial === decodedControl.serial, "registered ID serial class differs from full C/ISA decode")
        }
    }
    val rrFire = rrValid && (!exValid || exFire) && !olderSerial && !activeRecovery && !completionFault
    val issueReady = if (p.registerReadStage) !rrValid || rrFire else !exValid || exFire
    // EX redirects kill younger valid bits at the edge, rather than propagating the
    // operand/comparison path through frontend capacity. Speculative RF reads are safe:
    // they have no architectural effects, and their younger EX owner is killed below.
    val idLocalPermission = !olderSerial && !(rrValid && rrPacket.control.serial) && !serialDrain
    // Absorb duplicate live-owner gates rather than cascading rrFire ->
    // idFire -> ifFire -> reply READY. This is exact lookahead, not a
    // registered guess, added slot or lost-throughput timing shortcut.
    val idCapacity = if (p.fpgaTimingCuts) I1ExecuteDatapath.backendCapacity(
        rrValid, exValid, addrValid, memValid, memComplete, executeLocalReady, backendProgress)
        else issueReady
    val frontPermission = !quiesceBlocking && !activeRecovery && !csr.io.irqPending && !wbFenceI
    val idFire = idValid && idCapacity && idLocalPermission && frontPermission
    val idRounding = Mux(decodedControl.funct3 === 7.U, csr.io.fpRounding, decodedControl.funct3)
    val idNumericalLegal = I1ExecuteDatapath.numericalLegal(idPacket.fetchError, decodedControl.legal,
        decodedControl.floating, csr.io.fpEnabled,
        decodedControl.fpExecute && I1FloatingPointDecode.usesRounding(decoder.io.instruction), idRounding)
    def captureExecutionMetadata(packet: FiveStageExecutePacket): Unit = {
        packet.expanded.foreach(_ := decoder.io.instruction)
        packet.resultMask.foreach(_ := I1ExecuteDatapath.resultMask(decodedControl.fpExecute,
            decodedControl.jump, decodedControl.csr, decodedControl.mulDiv))
        packet.operandEnable.foreach(_ := Cat(decodedControl.usesRs2 && decodedControl.rs2 =/= 0.U,
            decodedControl.usesRs1 && decodedControl.rs1 =/= 0.U))
        packet.numericalLegal.foreach(_ := idNumericalLegal)
        packet.numericalRounding.foreach(_ := idRounding)
    }
    rf.io.readEnable := idFire; rf.io.rs1 := decodedControl.rs1; rf.io.rs2 := decodedControl.rs2
    fpr.foreach { registers =>
        registers.io.readEnable := idFire && decodedControl.floating
        registers.io.rs1 := decoder.io.instruction(19, 15)
        registers.io.rs2 := decoder.io.instruction(24, 20)
        registers.io.rs3 := decoder.io.instruction(31, 27)
    }
    when(idFire) {
        if (p.registerReadStage) {
            rrValid := true.B; rrPacket.instruction := idPacket; rrPacket.control := decodedControl
            rrCaptured := false.B
            captureExecutionMetadata(rrPacket)
        } else {
            exValid := true.B; exPacket.instruction := idPacket; exPacket.control := decodedControl
            mulDivSent := false.B; operandHeld := false.B
            captureExecutionMetadata(exPacket)
            if (p.withF) { fpSent := false.B }
        }
        idValid := false.B
    }
    if (p.registerReadStage) {
        val rc = rrPacket.control
        val readLeft = Mux(wbMatch(rc.rs1, rc.usesRs1), wbPacket.result, Mux(rrCaptured, rrLeft, rf.io.data1))
        val readRight = Mux(wbMatch(rc.rs2, rc.usesRs2), wbPacket.result, Mux(rrCaptured, rrRight, rf.io.data2))
        when(rrValid && !idFire) { rrLeft := readLeft; rrRight := readRight; rrCaptured := true.B }
        when(rrFire) {
            exValid := true.B; exPacket := rrPacket
            exLeft := (if (p.fpgaTimingCuts) Mux(rrPacket.operandEnable.get(0), readLeft, 0.U) else readLeft)
            exRight := (if (p.fpgaTimingCuts) Mux(rrPacket.operandEnable.get(1), readRight, 0.U) else readRight)
            if (p.fpgaTimingCuts) {
                heldLeft := Mux(rrPacket.operandEnable.get(0), readLeft, 0.U)
                heldRight := Mux(rrPacket.operandEnable.get(1), readRight, 0.U)
            }
            exFloatingOperands.foreach { captured =>
                when(rc.floating) {
                    captured := VecInit(Seq(fpr.get.io.data1, fpr.get.io.data2, fpr.get.io.data3))
                }
            }
            mulDivSent := false.B; operandHeld := false.B
            if (p.withF) { fpSent := false.B }
            when(!idFire) { rrValid := false.B }
        }
        if (p.fpgaTimingCuts) {
            // Compare register identities at the EXISTING RF->EX edge.
            // Retained EX operands follow only real backend movements, not
            // repeated rd comparisons ahead of the ALU on every cycle.
            // Producer availability remains a separate live admission test.
            val completionAdvance = cmpValid && !activeRecovery
            def advance(mask: UInt): UInt = VecInit(Seq(
                mask(0) && !addressFire,
                (mask(0) && addressFire) || (mask(1) && !memFire),
                (mask(1) && memFire) || (mask(2) && !completionAdvance),
                mask(2) && completionAdvance && !completionFault)).asUInt
            def nextProducer(index: UInt, used: Bool): UInt = {
                def writes(control: FiveStageDecodeControl): Bool =
                    used && index =/= 0.U && control.writesRd && control.rd === index
                val offers = Seq(
                    Mux(exFire, writes(c), addrValid && !addressFire && writes(addrPacket.control)),
                    Mux(addressFire, writes(addrPacket.control),
                        memValid && !memFire && writes(memPacket.control)),
                    Mux(memFire, writes(memPacket.control),
                        cmpValid && !completionAdvance && writes(cmpPacket.completion.control)),
                    completionAdvance && !completionFault && writes(cmpPacket.completion.control))
                VecInit(I1ExecuteDatapath.operandMasksWhen(true.B, offers)).asUInt
            }
            def aluSelection(mask: UInt, overrideEnable: Bool): UInt =
                VecInit((0 until 4).map(i => mask(i) && !overrideEnable) ++
                    Seq(!mask.orR && !overrideEnable, overrideEnable)).asUInt
            when(exValid && !exFire) {
                leftProducer.get := advance(leftProducer.get)
                rightProducer.get := advance(rightProducer.get)
                leftAluSelect.get := aluSelection(advance(leftProducer.get), c.usePc)
                rightAluSelect.get := aluSelection(advance(rightProducer.get), c.useImmediate)
            }
            when(rrFire) {
                leftProducer.get := nextProducer(rc.rs1, rc.usesRs1)
                rightProducer.get := nextProducer(rc.rs2, rc.usesRs2)
                leftAluSelect.get := aluSelection(nextProducer(rc.rs1, rc.usesRs1), rc.usePc)
                rightAluSelect.get := aluSelection(nextProducer(rc.rs2, rc.usesRs2), rc.useImmediate)
            }
        }
    }
    val ifCapacity = if (p.fpgaTimingCuts) !idValid || (idLocalPermission && idCapacity)
        else !idValid || idFire
    val frontendAccept = frontPermission && ifCapacity
    val ifFire = ifValid && frontendAccept
    when(ifFire) {
        idValid := true.B; idPacket := ifPacket; ifValid := false.B
        idSerial.foreach(_ := I1SerialPredecode(ifPacket.instruction, ifPacket.compressed, p))
    }

    // An offered request is never withdrawn under READY backpressure, even on a redirect.
    // Killed read owners drain with their original PC; they cannot become valid instructions.
    val desiredPc = RegInit(p.resetVector.U(p.xlen.W))
    val offerValid = RegInit(true.B)
    val offerPc = RegInit(p.resetVector.U(p.xlen.W))
    val offerKilled = RegInit(false.B)
    val pending = RegInit(false.B)
    val pendingPc = Reg(UInt(p.xlen.W))
    val pendingPrediction = Reg(UInt(p.xlen.W))
    val pendingKilled = RegInit(false.B)
    val predictedNext = WireDefault(if (p.fpgaTimingCuts)
        I1TimingMath.incrementPowerOfTwo(offerPc, 2) else offerPc + 4.U)
    val predictionCount = if (p.fpgaTimingCuts && p.branchPredictorEntries > 0)
        math.min(4, p.branchPredictorEntries / 2) + 2 else 1
    val predictionValues = WireDefault(VecInit(Seq.fill(predictionCount)(0.U(p.xlen.W))))
    val predictionMask = WireDefault(1.U(predictionCount.W))
    predictionValues(0) := predictedNext
    if (p.branchPredictorEntries > 0) {
        val predictor = Module(new FiveStageBranchPredictor(p))
        predictor.io.pc := offerPc
        predictor.io.invalidate := io.invalidateInstructionCache
        predictor.io.train.valid := wbCommit && !wbPacket.fault
        predictor.io.train.bits.pc := wbPacket.instruction.pc
        predictor.io.train.bits.controlFlow := wbPacket.control.branch || wbPacket.control.jump
        predictor.io.train.bits.conditional := wbPacket.control.branch
        predictor.io.train.bits.taken := wbPacket.branchTaken
        predictor.io.train.bits.target := wbPacket.branchTarget
        predictor.io.train.bits.compressed := wbPacket.instruction.compressed
        predictedNext := predictor.io.nextPc
        if (p.fpgaTimingCuts) {
            predictionValues := VecInit(predictor.io.candidateValues.get.all)
            predictionMask := predictor.io.candidateMask.get
        }
    }
    if (p.externalFenceICompletion) fenceIFetchDrained := !offerValid && !pending
    val responseSpace = if (externalQuiesce)
        pendingKilled || wbFenceI || quiesceBlocking || !ifValid || (if (p.fpgaTimingCuts) frontendAccept else ifFire)
        else pendingKilled || wbFenceI || !ifValid || (if (p.fpgaTimingCuts) frontendAccept else ifFire)
    io.instructionResponse.ready := pending && responseSpace
    io.instructionRequest.valid := offerValid && (if (p.fpgaTimingCuts)
        !pending || (io.instructionResponse.valid && responseSpace) else !pending || io.instructionResponse.fire)
    io.instructionRequest.bits := offerPc
    when(io.instructionResponse.fire) {
        pending := false.B
        when(!pendingKilled && !flush && !wbFenceI && !quiesceBlocking) {
            ifValid := true.B; ifPacket.pc := pendingPc
            ifPacket.instruction := io.instructionResponse.bits.instruction
            ifPacket.fetchError := io.instructionResponse.bits.error
            ifPacket.fetchPageFault := io.instructionResponse.bits.pageFault
            ifPacket.compressed := p.withC.B && io.instructionResponse.bits.compressed
            ifPacket.fetchSecondHalfFault := io.instructionResponse.bits.secondHalfFault
            ifPacket.predictedNextPc := (if (p.branchPredictorEntries > 0 || p.withC) pendingPrediction else 0.U)
        }
    }
    when(!offerValid && !csr.io.irqPending && !flush && !wbFenceI && !quiesceBlocking) {
        offerValid := true.B; offerKilled := false.B
        if (!p.fpgaTimingCuts) offerPc := desiredPc
    }
    when(io.instructionRequest.fire) {
        pending := true.B; pendingPc := offerPc; pendingKilled := offerKilled || flush || wbFenceI || quiesceBlocking
        pendingPrediction := predictedNext
        offerValid := !csr.io.irqPending && !wbFenceI && !quiesceBlocking; offerKilled := false.B
        if (!p.fpgaTimingCuts) {
            offerPc := Mux(offerKilled, desiredPc, predictedNext)
            when(!offerKilled) { desiredPc := predictedNext }
        }
    }
    if (p.externalFenceICompletion) when(wbFenceI) {
        // Preserve every already-offered request until accepted, then drain its killed
        // reply even with full IF/ID. No new offer may keep PTW/cache maintenance alive.
        ifValid := false.B; idValid := false.B
        when(pending && !io.instructionResponse.fire) { pendingKilled := true.B }
        when(offerValid && !io.instructionRequest.fire) { offerKilled := true.B }
    }
    when(flush) {
        ifValid := false.B; idValid := false.B
        if (!p.fpgaTimingCuts) desiredPc := redirectPc
        when(pending && !io.instructionResponse.fire) { pendingKilled := true.B }
        when(offerValid && !io.instructionRequest.fire) { offerKilled := true.B }
            .otherwise {
                offerValid := true.B; offerKilled := false.B
                if (!p.fpgaTimingCuts) offerPc := redirectPc
            }
    }
    if (p.fpgaTimingCuts) {
        // Prepare data independently of the late IT/cache acceptance.
        // The real handshake only enables the existing registers: feeding
        // FIRE into every candidate mask reintroduced permission -> READY
        // -> wide payload mux -> hold mux on the PC feedback path.
        val predict = io.instructionRequest.fire && !offerKilled && !flush && !wbFenceI && !quiesceBlocking
        val resume = !flush && !wbFenceI && !quiesceBlocking && ((!offerValid && !csr.io.irqPending) ||
            (io.instructionRequest.fire && offerKilled))
        val redirect = flush && (!offerValid || io.instructionRequest.fire)
        when(predict || resume || redirect) {
            offerPc := Mux(flush, redirectPc,
                Mux(offerKilled || !offerValid, desiredPc, predictedNext))
        }
        when(predict || flush) {
            desiredPc := Mux(flush, redirectPc, predictedNext)
        }
    }
    if (externalQuiesce) {
        // Cut only unexecuted IF/ID work. Already offered requests remain stable;
        // accepted fetch replies are consumed as killed, while every backend
        // owner continues to its original completion/retirement or recovery.
        when(quiesceBlocking) {
            ifValid := false.B; idValid := false.B
            when(pending && !io.instructionResponse.fire) { pendingKilled := true.B }
            when(offerValid && !io.instructionRequest.fire) { offerKilled := true.B }
            when(!offerValid || io.instructionRequest.fire) { offerValid := false.B }
        }
        val stopped = quiesceRequest && !stages.reduce(_ || _) && !offerValid && !pending &&
            !wbRecovery.getOrElse(false.B)
        io.architecturalStopped.get := stopped
        val stoppedPrevious = RegNext(stopped, false.B)
        when(quiesceRelease) {
            assert(stoppedPrevious, "external quiesce request withdrawn before architectural stop")
            // Include the last retired branch/trap/xRET recovery, not the stale
            // speculative desired PC. The release edge itself admits no work.
            offerValid := true.B; offerKilled := false.B
            offerPc := architecturalNextPc; desiredPc := architecturalNextPc
        }
        when(stopped) {
            assert(!io.retire.valid && !io.trapTaken && !io.dataRequest.valid && !io.instructionRequest.valid,
                "architectural side effect or request while stopped")
        }
    }
    when(backendFlush) { exValid := false.B; mulDivSent := false.B; operandHeld := false.B }
    if (p.withF) when(backendFlush) { fpSent := false.B }
    if (p.registerReadStage) when(backendFlush) { rrValid := false.B; rrCaptured := false.B }
    if (p.addressStage) when(activeRecovery) { addrValid := false.B }
    // EX capacity is speculative and independent of ADDR's redirect/kill.
    // The resolving branch already transfers to MEM. Discard only the younger
    // replacement ADDR packet at this edge, before it can issue any data request.
    if (p.fpgaTimingCuts) when(exRedirect) { addrValid := false.B }
    if (p.completionStage) when(activeRecovery) { cmpValid := false.B }
    when(activeRecovery) { memValid := false.B }
    io.stallLoadUse := exValid && dependency && ((memValid && (memPacket.control.load || memPacket.control.atomic)) ||
        (addrValid && (addrPacket.control.load || addrPacket.control.atomic)) ||
        (cmpValid && (cmpPacket.completion.control.load || cmpPacket.completion.control.atomic)))
    io.stallMemory := memValid && !memComplete
    io.stallMulDiv := exValid && c.mulDiv && !mulComplete && !exFault
    io.stallFetch := pending && !io.instructionResponse.valid
    io.stallStoreAck := memValid && memPacket.control.store && memSent && !io.dataResponse.valid
    io.dataRequestAccepted := io.dataRequest.fire
    io.dataRequestOffered := io.dataRequest.valid
    when(!reset.asBool) {
        if (p.fpgaTimingCuts) {
            when(memValid) {
                assert(memReplyRequired === (memAccess && !memPacket.fault),
                    "registered MEM reply classification differs from the live owner")
            }
            assert(completionFault === (cmpValid &&
                (cmpPacket.completion.fault || cmpPacket.accessed && cmpPacket.response.error)),
                "registered CMP fault omitted a real access error")
            assert(idFire === (idValid && issueReady && idLocalPermission && frontPermission),
                "lookahead ID capacity differs from exact owner transfer")
            assert(exFire === (exValid && executeReady && executeLocalReady && backendProgress),
                "flattened EX capacity differs from exact owner transfer")
            assert(ifFire === (ifValid && (!idValid || idFire) && frontPermission),
                "lookahead IF capacity differs from exact owner transfer")
            assert(io.instructionResponse.ready === (pending && (if (externalQuiesce)
                pendingKilled || wbFenceI || quiesceBlocking || !ifValid || ifFire
                else pendingKilled || wbFenceI || !ifValid || ifFire)),
                "lookahead fetch reply capacity mismatch")
            assert(io.instructionRequest.valid === (offerValid && (!pending || io.instructionResponse.fire)),
                "lookahead fetch request slot mismatch")
            when(exValid) {
                assert(exPacket.operandEnable.get === Cat(c.usesRs2 && c.rs2 =/= 0.U, c.usesRs1 && c.rs1 =/= 0.U),
                    "registered register-source qualification mismatch")
                when(c.mulDiv || c.fpExecute) {
                    assert(!(c.mulDiv && c.fpExecute) && !c.csr && !c.ecall && !c.ebreak &&
                        !c.mret && !c.sret && !c.sfence && !c.wfi && !c.fenceI,
                        "numerical decode owner overlaps CSR/system class")
                    assert(numericalFault === instructionFault, "captured numerical legality changed before EX")
                }
                if (p.withF) when(c.fpExecute) {
                    assert(numericalRounding === fpRounding, "captured floating rounding context changed before EX")
                }
            }
            assert(!irqCommit || (!mulDivSent && !fpSent),
                "empty-backend IRQ still has a numerical owner")
            assert(!irqCommit || (!memSent || !memValid),
                "empty-backend IRQ still has a memory owner")
        }
        if (p.overlapDataRetirement) {
            when(earlyRequest && memValid && memAccess) {
                assert(io.dataResponse.fire && !io.dataResponse.bits.error &&
                    !memPacket.control.serial && !memPacket.fault,
                    "replacement request bypassed unsuccessful/serial memory retirement")
                if (p.readOnlyDataRetirement) {
                    assert(memPacket.control.load && !memPacket.control.store && !earlyBits.write,
                        "read-only replacement changed a store scheduling boundary")
                }
            }
        }
        wbRecovery.foreach { recovery =>
            assert(recovery === (wbValid && needsRecovery(wbPacket)), "registered WB recovery owner mismatch")
            assert(!io.dataRequest.fire || selectEarlyPayload === (earlyRequest || readAhead),
                "early memory payload must match the actual admitted owner")
            when(exValid) {
                assert(exPacket.resultMask.get === I1ExecuteDatapath.resultMask(
                    c.fpExecute, c.jump, c.csr, c.mulDiv), "registered EX result selection mismatch")
            }
        }
        assert(!io.dataResponse.valid || (memValid && memSent), "data response has no MEM owner")
        assert(!io.instructionResponse.valid || pending, "instruction response has no IF owner")
        assert(!io.dataRequest.fire || Mux(earlyRequest || readAhead,
            (if (p.addressStage) !addressPrepared.fault else !exFault), !memPacket.fault),
            "faulting instruction issued a data request")
        assert(!earlyRequest || (earlySlotAvailable && (if (p.addressStage) addressFire else exFire) &&
            !olderFlush && !completionFault), "early memory ownership violation")
        assert(!io.dataRequest.fire || !completionFault, "younger memory side effect bypassed an older CMP fault")
        addressSent.foreach { sent =>
            when(sent) {
                assert(addrValid && addrPacket.control.load && !addrPacket.control.store &&
                    !addrPacket.control.atomic && memValid && !activeRecovery && !completionFault,
                    "read handoff lost its existing ADDR/MEM ownership")
            }
        }
    }
}
