package soc.core.ooo

import chisel3._
import chisel3.util._

/** Small boundary proof. Scheduling metadata is deliberately not decoded from
  * instructions: all M/T/system/M-unit combinations are independently writable.
  * Capacity 1/lane, latency 1, II 1, with the real stage's unchanged cancel credit.
  * This is not a replacement for the full-backend load-forwarding acceptance.
  */
object RegisteredExecutionOperandProof {
    def params(parallel: Boolean, banked: Boolean): OooParams = OooParams(
        robEntries = 16, physicalRegs = 48, registeredBranchRedirect = true,
        registeredRobRetirement = true, precompleteMispredictedBranch = true,
        registeredIssueExecute = true, registeredLoadIssueForwarding = true,
        earlyRankedOperands = true, parallelIssuePayload = true,
        parallelIssueRanks = parallel, bankedIssuePayload = banked, lvtPhysicalRegisterFile = true)
    val entryBits = 462
    val payloadBits = entryBits + 129
}

class ExecutionOperandProofWake extends Bundle {
    val valid = Bool()
    val destination = UInt(6.W)
    val data = UInt(64.W)
}

class ExecutionOperandProofWrite extends Bundle {
    val valid = Bool()
    val address = UInt(6.W)
    val data = UInt(64.W)
}

// Scalar top-level fields avoid GSIM's unsupported nested Vec port accessors.
class ExecutionOperandProofInput extends Bundle {
    val rowValid = Bool()
    val rowIndex = UInt(4.W)
    val rowWord0 = UInt(64.W)
    val rowWord1 = UInt(64.W)
    val rowWord2 = UInt(64.W)
    val rowWord3 = UInt(64.W)
    val rowWord4 = UInt(64.W)
    val rowWord5 = UInt(64.W)
    val rowWord6 = UInt(64.W)
    val rowWord7 = UInt(64.W)
    def rowWords: Seq[UInt] = Seq(rowWord0, rowWord1, rowWord2, rowWord3, rowWord4, rowWord5, rowWord6, rowWord7)
    val write0 = new ExecutionOperandProofWrite
    val write1 = new ExecutionOperandProofWrite
    val head = UInt(4.W)
    val pending = UInt(16.W)
    val prepared = UInt(16.W)
    val addressKnown = UInt(16.W)
    val preparationBusy = UInt(16.W)
    val ready = UInt(48.W)
    val killed = UInt(16.W)
    val pendingException = Bool()
    val headException = Bool()
    val branchRedirect = Bool()
    val reserveSystem = Bool()
    val reserveMemory = Bool()
    val reserveMulDiv = Bool()
    val completeSystem = Bool()
    val completeMemory = Bool()
    val completeMulDiv = Bool()
    val sinkReady0 = Bool()
    val sinkReady1 = Bool()
    val load = new ExecutionOperandProofWake
    val alu0 = new ExecutionOperandProofWake
    val alu1 = new ExecutionOperandProofWake
    // Test-only RTL controls: none, store exclusion, load priority, shared store
    // operand, valid payload bit, and invalid held-output observation bit.
    val mutation = UInt(3.W)
}

class ExecutionOperandProofObservation extends Bundle {
    val opportunity = Bool()
    val enqValid = Bool()
    val enqReady = Bool()
    val enqFire = Bool()
    val deqValid = Bool()
    val deqReady = Bool()
    val deqFire = Bool()
    val occupied = Bool()
    val cancel = Bool()
    val offered0 = UInt(64.W)
    val offered1 = UInt(64.W)
    val offered2 = UInt(64.W)
    val offered3 = UInt(64.W)
    val offered4 = UInt(64.W)
    val offered5 = UInt(64.W)
    val offered6 = UInt(64.W)
    val offered7 = UInt(64.W)
    val offered8 = UInt(64.W)
    val offered9 = UInt(64.W)
    val held0 = UInt(64.W)
    val held1 = UInt(64.W)
    val held2 = UInt(64.W)
    val held3 = UInt(64.W)
    val held4 = UInt(64.W)
    val held5 = UInt(64.W)
    val held6 = UInt(64.W)
    val held7 = UInt(64.W)
    val held8 = UInt(64.W)
    val held9 = UInt(64.W)
    def offered: Seq[UInt] = Seq(offered0, offered1, offered2, offered3, offered4, offered5, offered6, offered7, offered8, offered9)
    def held: Seq[UInt] = Seq(held0, held1, held2, held3, held4, held5, held6, held7, held8, held9)
    val prepare = Bool()
    val storeBase = UInt(64.W)
    val storeData = UInt(64.W)
    val storeAddress = UInt(64.W)
    val mutationApplied = Bool()
}

class ExecutionOperandProofPair extends Bundle {
    val owner = UInt(16.W)
    val index = UInt(4.W)
    val rankValid = Bool()
    val reference = new ExecutionOperandProofObservation
    val candidate = new ExecutionOperandProofObservation
}

class ExecutionOperandProofConfiguration extends Bundle {
    val eligible = UInt(16.W)
    val lane0 = new ExecutionOperandProofPair
    val lane1 = new ExecutionOperandProofPair
}

class RegisteredExecutionOperandSlice(parallel: Boolean, banked: Boolean) extends Module {
    import RegisteredExecutionOperandProof._
    val p = params(parallel, banked)
    val on = p.copy(directRegisteredExecutionOperands = true)
    require((new IntegerIssueEntry(p)).getWidth == entryBits)
    require((new IntegerExecutionOperands(p)).getWidth == payloadBits)
    val io = IO(new Bundle {
        val in = Input(new ExecutionOperandProofInput)
        val out = Output(new ExecutionOperandProofConfiguration)
    })
    val in = io.in
    val queue = Reg(Vec(p.robEntries, new IntegerIssueEntry(p)))
    val written = VecInit(in.rowWords).asUInt(entryBits - 1, 0).asTypeOf(new IntegerIssueEntry(p))
    when(in.rowValid) {
        queue(in.rowIndex) := written
        if (banked) {
            ImmutableIssuePayload.insert(queue(in.rowIndex).request, 0.U.asTypeOf(new ImmutableIssuePayload))
        }
    }
    val payload = if (banked) Some(Module(new BankedIssuePayload(p.robEntries,
        Seq.fill(2)(ImmutableIssuePayload.execution)))) else None
    payload.foreach { ram =>
        ram.io.write := 0.U.asTypeOf(ram.io.write)
        ram.io.write(0).valid := in.rowValid
        ram.io.write(0).bits.index := in.rowIndex
        ram.io.write(0).bits.data := ImmutableIssuePayload.fromRequest(written.request)
    }
    val prf = Module(new OwnerBankedPhysicalRegisterFile(p.physicalRegs, readPorts = 4))
    for ((write, lane) <- Seq(in.write0, in.write1).zipWithIndex) {
        prf.io.write(lane).valid := write.valid
        prf.io.write(lane).bits.address := write.address
        prf.io.write(lane).bits.data := write.data
    }
    def baseReady(source: UInt): Bool = Mux(source < p.physicalRegs.U, in.ready(source), false.B)
    def hit(wake: ExecutionOperandProofWake, source: UInt): Bool = wake.valid && wake.destination === source
    def issueReady(source: UInt): Bool = baseReady(source) || hit(in.load, source) ||
        hit(in.alu0, source) || hit(in.alu1, source)
    // Overlapping load/ALU destinations below are an intentional component
    // priority stress. The full backend rejects such conflicting live producer
    // ownership; this fixture does not claim that overlap is a legal workload.
    def forwarded(source: UInt, stored: UInt, corruptPriority: Bool): UInt = {
        val aluHit = hit(in.alu0, source) || hit(in.alu1, source)
        val aluData = Mux1H(Seq(hit(in.alu0, source) -> in.alu0.data, hit(in.alu1, source) -> in.alu1.data))
        val loadFirst = Mux(hit(in.load, source), in.load.data, Mux(aluHit, aluData, stored))
        Mux(corruptPriority && aluHit, aluData, loadFirst)
    }
    val eligible = VecInit((0 until p.robEntries).map { i =>
        val e = queue(i)
        val prepareStore = e.request.memory && e.request.store && !in.prepared(i) && i.U =/= in.head
        val source1 = Mux(in.pending(i), e.renamed.source1, 0.U)
        val source2 = Mux(in.pending(i), e.renamed.source2, 0.U)
        val firstReady = e.request.usePc || Mux(e.request.memory, baseReady(source1), issueReady(source1))
        val secondReady = e.request.useImmediate || Mux(e.request.memory, baseReady(source2), issueReady(source2))
        in.pending(i) && !e.request.system && !e.request.mulDiv && (!e.request.memory || prepareStore) &&
            firstReady && (secondReady || (prepareStore && !in.addressKnown(i))) && !in.preparationBusy(i) &&
            (!in.branchRedirect || e.request.controlFlow === ControlFlow.none)
    })
    val selector = Module(new CircularIssueSelector(p, parallelRanks = parallel))
    selector.io.head := in.head
    selector.io.eligible := eligible.asUInt
    io.out.eligible := eligible.asUInt
    for ((observation, lane) <- Seq(io.out.lane0, io.out.lane1).zipWithIndex) {
        val owner = if (lane == 0) selector.io.second else selector.io.first
        val index = if (lane == 0) selector.io.secondIndex else selector.io.firstIndex
        val rankValid = if (lane == 0) selector.io.secondValid else selector.io.firstValid
        val metadata = CircularIssueSelector.selectPayload(owner, queue.map(_.asUInt).toSeq)
            .asTypeOf(new IntegerIssueEntry(p))
        val entry = WireDefault(metadata)
        payload.foreach { ram =>
            ram.io.address(lane) := index
            ram.io.enable(lane) := owner.orR
            ImmutableIssuePayload.insert(entry.request, ram.io.data(lane))
        }
        observation.owner := owner
        observation.index := index
        observation.rankValid := rankValid
        val source1 = entry.renamed.source1
        val source2 = entry.renamed.source2
        prf.io.address(2 * lane) := source1
        prf.io.address(2 * lane + 1) := source2
        val storedLeft = prf.io.data(2 * lane)
        val storedRight = prf.io.data(2 * lane + 1)
        val dispatchLeft = Mux(entry.request.memory, storedLeft, forwarded(source1, storedLeft, false.B))
        val dispatchRight = Mux(entry.request.memory, storedRight, forwarded(source2, storedRight, false.B))
        val opportunity = rankValid && (if (lane == 0) !in.branchRedirect &&
            !(in.reserveSystem || in.reserveMemory || in.reserveMulDiv) else true.B)
        val store = entry.request.memory && entry.request.store
        val legal = Module(new IntegerAlu)
        legal.io.operation := entry.request.operation
        legal.io.word := entry.request.word
        legal.io.left := 0.U
        legal.io.right := 0.U
        for ((out, direct) <- Seq(observation.reference -> false, observation.candidate -> true)) {
            val side = if (direct) on else p
            val mutation = Mux(direct.B, in.mutation, 0.U)
            val stage = Module(new IssueExecuteStage(payloadBits))
            val incoming = Wire(new IntegerExecutionOperands(p))
            incoming.entry := entry
            incoming.left := (if (side.directRegisteredExecutionOperands)
                forwarded(source1, storedLeft, mutation === 2.U) else dispatchLeft)
            incoming.right := (if (side.directRegisteredExecutionOperands)
                forwarded(source2, storedRight, mutation === 2.U) else dispatchRight)
            incoming.forwardable := entry.renamed.writesRd && entry.request.controlFlow === ControlFlow.none &&
                !entry.request.fetchFault && !entry.request.fetchPageFault && legal.io.legal
            val enqValid = opportunity && (mutation === 1.U || !store) &&
                !in.killed(index) && !in.pendingException
            val payloadMutation = mutation === 4.U && enqValid
            stage.io.enq.valid := enqValid
            stage.io.enq.bits := incoming.asUInt ^ Mux(payloadMutation, (BigInt(1) << 257).U(payloadBits.W), 0.U)
            val held = stage.io.deq.bits.asTypeOf(new IntegerExecutionOperands(p))
            val ownerIndex = Mux(stage.io.occupied, held.entry.renamed.token.index, 0.U)
            val stale = queue(ownerIndex).renamed.token.asUInt =/= held.entry.renamed.token.asUInt
            stage.io.cancel := stage.io.occupied && (in.killed(ownerIndex) || stale)
            stage.io.deq.ready := (if (lane == 0) in.sinkReady0 &&
                !(in.completeMemory || in.completeMulDiv || in.completeSystem) else in.sinkReady1) &&
                (!in.branchRedirect || held.entry.request.controlFlow === ControlFlow.none)
            val storeMutation = mutation === 3.U && store
            val storeLeft = Mux(storeMutation, forwarded(source1, storedLeft, false.B), dispatchLeft)
            val storeRight = Mux(storeMutation, forwarded(source2, storedRight, false.B), dispatchRight)
            val heldMutation = mutation === 5.U && !stage.io.occupied && stage.io.deq.bits.orR
            // This control corrupts a real RTL observation, including unoccupied
            // stale output. It does not silently change the independent oracle.
            val observedHeld = stage.io.deq.bits ^ Mux(heldMutation, (BigInt(1) << 30).U(payloadBits.W), 0.U)
            out.opportunity := opportunity
            out.enqValid := stage.io.enq.valid
            out.enqReady := stage.io.enq.ready
            out.enqFire := stage.io.enq.fire
            out.deqValid := stage.io.deq.valid
            out.deqReady := stage.io.deq.ready
            out.deqFire := stage.io.deq.fire
            out.occupied := stage.io.occupied
            out.cancel := stage.io.cancel
            for (word <- 0 until 10) {
                out.offered(word) := stage.io.enq.bits.pad(640)(64 * word + 63, 64 * word)
                out.held(word) := observedHeld.pad(640)(64 * word + 63, 64 * word)
            }
            out.prepare := opportunity && store && !in.killed(index) && !in.headException
            out.storeBase := storeLeft
            out.storeData := storeRight
            out.storeAddress := storeLeft + entry.request.immediate
            out.mutationApplied := (mutation === 1.U && opportunity && store && !in.killed(index) &&
                !in.pendingException) || (mutation === 2.U &&
                (incoming.left =/= forwarded(source1, storedLeft, false.B) ||
                    incoming.right =/= forwarded(source2, storedRight, false.B))) ||
                (storeMutation && (storeLeft =/= dispatchLeft || storeRight =/= dispatchRight)) ||
                payloadMutation || heldMutation
        }
    }
}

class RegisteredExecutionOperandPairGsim extends Module {
    val io = IO(new Bundle {
        val in = Input(new ExecutionOperandProofInput)
        val cfg0 = Output(new ExecutionOperandProofConfiguration)
        val cfg1 = Output(new ExecutionOperandProofConfiguration)
        val cfg2 = Output(new ExecutionOperandProofConfiguration)
        val cfg3 = Output(new ExecutionOperandProofConfiguration)
    })
    for ((out, index) <- Seq(io.cfg0, io.cfg1, io.cfg2, io.cfg3).zipWithIndex) {
        val slice = Module(new RegisteredExecutionOperandSlice(parallel = (index & 1) != 0,
            banked = (index & 2) != 0))
        slice.io.in := io.in
        out := slice.io.out
    }
}
