package soc.core.ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import _root_.ooo.LoadReadyBackendBaseGsim

/** Prepared only: use the real backend/LSU/rename path, never force internal grants. */
object LoadReadyBackendFixture {
    def params(enabled: Boolean): OooParams = BoardSocConfig.timingParams("staged-load-issue").copy(
        robEntries = 16, physicalRegs = 48, memoryEntries = 4, tagBits = 64,
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 65536,
        lvtPhysicalRegisterFile = true, bankedIssuePayload = true, bankedRobPayload = true,
        sharedStoreOperandReads = true, ownerLocalIssueReady = true,
        directRegisteredExecutionOperands = true, sharedLane1OwnerMatch = true,
        heldAluIssueForwarding = true, registeredLoadResultReady = enabled)
    def write(target: String, enabled: Boolean): Unit = {
        java.nio.file.Files.createDirectories(java.nio.file.Paths.get(target))
        val fields = params(enabled).productElementNames.zip(params(enabled).productIterator).map { case (k, v) =>
            s"\"$k\":\"${v.toString.replace("\\", "\\\\").replace("\"", "\\\"")}\""
        }.mkString(",\n")
        java.nio.file.Files.writeString(java.nio.file.Paths.get(target, "parameters.json"), s"{\n$fields\n}\n")
    }
}

class LoadReadyLaneObservation(p: OooParams) extends Bundle {
    val occupied = Bool()
    val cancel = Bool()
    val enqValid = Bool()
    val enqReady = Bool()
    val deqValid = Bool()
    val deqReady = Bool()
    val heldToken = new RobToken(p)
    val heldDestination = UInt(p.physBits.W)
    val heldForwardable = Bool()
    val heldLeft = UInt(64.W)
    val heldRight = UInt(64.W)
    val heldResult = UInt(64.W)
    val heldDestinationReady = Bool()
    val promiseValid = Bool()
    val promiseDestination = UInt(p.physBits.W)
    val incomingToken = new RobToken(p)
    val incomingSource1 = UInt(p.physBits.W)
    val incomingSource2 = UInt(p.physBits.W)
    val incomingUsePc = Bool()
    val incomingUseImmediate = Bool()
    val incomingLeft = UInt(64.W)
    val incomingRight = UInt(64.W)
    val incomingMemory = Bool()
    val prepared = Bool()
    val storePrepareToken = new RobToken(p)
    val storePrepareBase = UInt(64.W)
    val storePrepareImmediate = UInt(64.W)
    val storePrepareData = UInt(64.W)
    val storePrepareDataReady = Bool()
    val capturedHeld0Mask = UInt(2.W)
    val actualCompletionValid = Bool()
    val actualCompletionAccepted = Bool()
    val actualCompletionToken = new RobToken(p)
    val actualCompletionException = Bool()
    val prfWriteValid = Bool()
    val prfWriteDestination = UInt(p.physBits.W)
    val prfWriteData = UInt(64.W)
}

class LoadReadyMemoryStart(p: OooParams) extends Bundle {
    val fire = Bool()
    val token = new RobToken(p)
    val address = UInt(64.W)
    val data = UInt(64.W)
    val store = Bool()
}

class LoadReadyMStart(p: OooParams) extends Bundle {
    val fire = Bool()
    val token = new RobToken(p)
    val left = UInt(64.W)
    val right = UInt(64.W)
}

class LoadReadySlotObservation(p: OooParams) extends Bundle {
    val owner = new RobToken(p)
    val result = new BackendCompletion(p)
    val phase = UInt(2.W)
    val start = Bool()
    val request = Bool()
    val startForward = Bool()
    val response = Bool()
    val completeValid = Bool()
    val completeReady = Bool()
    val cancelled = Bool()
    val cancel = Bool()
    val savedDestination = Valid(UInt(p.physBits.W))
    val held = Valid(new Bundle { val destination = UInt(p.physBits.W); val data = UInt(64.W) })
    val publish = Valid(UInt(p.physBits.W))
}
class LoadReadyRowObservation(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    val source1 = UInt(p.physBits.W)
    val source2 = UInt(p.physBits.W)
    val memory = Bool()
    val store = Bool()
    val mulDiv = Bool()
    val system = Bool()
    val usePc = Bool()
    val useImmediate = Bool()
}

/** Integer bare fixture; VM/system/permission coverage remains an integration gate. */
class LoadReadyBackendGsim(enabled: Boolean)
    extends LoadReadyBackendBaseGsim(LoadReadyBackendFixture.params(enabled), eventBoundReplies = true) {
    val fixtureParams = LoadReadyBackendFixture.params(enabled)
    require(!fixtureParams.machineSystem && fixtureParams.virtualMemoryLevels == 0 &&
        !fixtureParams.virtualRamLoadPrecheck && !fixtureParams.taggedStoreReturns)
    require(backend.p == fixtureParams && backend.ledger.p == fixtureParams)
    val observation0 = IO(Output(new LoadReadyLaneObservation(fixtureParams)))
    val observation1 = IO(Output(new LoadReadyLaneObservation(fixtureParams)))
    val rawLsuCompletion = IO(Output(Bool()))
    val rawDividerCompletion = IO(Output(Bool()))
    val rawMultiplierCompletion = IO(Output(Bool()))
    val memoryStart = IO(Output(new LoadReadyMemoryStart(fixtureParams)))
    val multiplierStart = IO(Output(new LoadReadyMStart(fixtureParams)))
    val dividerStart = IO(Output(new LoadReadyMStart(fixtureParams)))
    val physicalReadyMask = IO(Output(UInt(fixtureParams.physicalRegs.W)))
    val pendingMask = IO(Output(UInt(fixtureParams.robEntries.W)))
    val killedMask = IO(Output(UInt(fixtureParams.robEntries.W)))
    val storePreparedMask = IO(Output(UInt(fixtureParams.robEntries.W)))
    rawLsuCompletion := BoringUtils.bore(backend.lsu.io.complete.valid)
    rawDividerCompletion := BoringUtils.bore(backend.mulDiv.io.complete.valid)
    rawMultiplierCompletion := BoringUtils.bore(backend.multiplier.io.complete.valid)

    val promises = BoringUtils.bore(backend.executionWake)
    val results = BoringUtils.bore(backend.executionData)
    val physicalReady = BoringUtils.bore(backend.ready)
    physicalReadyMask := physicalReady.asUInt
    pendingMask := BoringUtils.bore(backend.pending).asUInt
    killedMask := BoringUtils.bore(backend.killed).asUInt
    storePreparedMask := BoringUtils.bore(backend.storePrepared).asUInt
    memoryStart.fire := BoringUtils.bore(backend.lsu.io.start.valid) &&
        BoringUtils.bore(backend.lsu.io.start.ready)
    memoryStart.token := BoringUtils.bore(backend.lsu.io.start.bits.token)
    memoryStart.address := BoringUtils.bore(backend.lsu.io.start.bits.address)
    memoryStart.data := BoringUtils.bore(backend.lsu.io.start.bits.data)
    memoryStart.store := BoringUtils.bore(backend.lsu.io.start.bits.store)
    multiplierStart.fire := BoringUtils.bore(backend.multiplier.io.start.valid) &&
        BoringUtils.bore(backend.multiplier.io.start.ready)
    multiplierStart.token := BoringUtils.bore(backend.multiplier.io.start.bits.token)
    multiplierStart.left := BoringUtils.bore(backend.multiplier.io.start.bits.left)
    multiplierStart.right := BoringUtils.bore(backend.multiplier.io.start.bits.right)
    dividerStart.fire := BoringUtils.bore(backend.mulDiv.io.start.valid) &&
        BoringUtils.bore(backend.mulDiv.io.start.ready)
    dividerStart.token := BoringUtils.bore(backend.mulDiv.io.start.bits.token)
    dividerStart.left := BoringUtils.bore(backend.mulDiv.io.start.bits.left)
    dividerStart.right := BoringUtils.bore(backend.mulDiv.io.start.bits.right)
    val rowReady1 = IO(Output(UInt(fixtureParams.robEntries.W)))
    val rowReady2 = IO(Output(UInt(fixtureParams.robEntries.W)))
    val memoryLiveMask = IO(Output(UInt(fixtureParams.robEntries.W)))
    val wake0 = IO(Output(Valid(UInt(fixtureParams.physBits.W))))
    val wake1 = IO(Output(Valid(UInt(fixtureParams.physBits.W))))
    val wake2 = IO(Output(Valid(UInt(fixtureParams.physBits.W))))
    val reserve0 = IO(Output(Valid(UInt(fixtureParams.physBits.W))))
    val reserve1 = IO(Output(Valid(UInt(fixtureParams.physBits.W))))
    val requestOwner = IO(Output(Valid(new RobToken(fixtureParams))))
    val selectedSlot = IO(Output(UInt(2.W)))
    val slot0 = IO(Output(new LoadReadySlotObservation(fixtureParams)))
    val slot1 = IO(Output(new LoadReadySlotObservation(fixtureParams)))
    val slot2 = IO(Output(new LoadReadySlotObservation(fixtureParams)))
    val slot3 = IO(Output(new LoadReadySlotObservation(fixtureParams)))
    val row0 = IO(Output(new LoadReadyRowObservation(fixtureParams)))
    val row1 = IO(Output(new LoadReadyRowObservation(fixtureParams)))
    val row2 = IO(Output(new LoadReadyRowObservation(fixtureParams)))
    val row3 = IO(Output(new LoadReadyRowObservation(fixtureParams)))
    val row4 = IO(Output(new LoadReadyRowObservation(fixtureParams)))
    val row5 = IO(Output(new LoadReadyRowObservation(fixtureParams)))
    val row6 = IO(Output(new LoadReadyRowObservation(fixtureParams)))
    val row7 = IO(Output(new LoadReadyRowObservation(fixtureParams)))
    val row8 = IO(Output(new LoadReadyRowObservation(fixtureParams)))
    val row9 = IO(Output(new LoadReadyRowObservation(fixtureParams)))
    val row10 = IO(Output(new LoadReadyRowObservation(fixtureParams)))
    val row11 = IO(Output(new LoadReadyRowObservation(fixtureParams)))
    val row12 = IO(Output(new LoadReadyRowObservation(fixtureParams)))
    val row13 = IO(Output(new LoadReadyRowObservation(fixtureParams)))
    val row14 = IO(Output(new LoadReadyRowObservation(fixtureParams)))
    val row15 = IO(Output(new LoadReadyRowObservation(fixtureParams)))
    rowReady1 := BoringUtils.bore(backend.ownerReady.get.io.ready1).asUInt
    rowReady2 := BoringUtils.bore(backend.ownerReady.get.io.ready2).asUInt
    memoryLiveMask := BoringUtils.bore(backend.memoryLive).asUInt
    Seq(wake0, wake1, wake2).zipWithIndex.foreach { case (out, lane) =>
        out := BoringUtils.bore(backend.readyUpdate.get.io.wake(lane))
    }
    Seq(reserve0, reserve1).zipWithIndex.foreach { case (out, lane) =>
        out := BoringUtils.bore(backend.readyUpdate.get.io.reserve(lane))
    }
    requestOwner := BoringUtils.bore(backend.lsu.io.requestOwner)
    selectedSlot := BoringUtils.bore(backend.lsu.completion.io.chosen)
    for ((out, i) <- Seq(slot0, slot1, slot2, slot3).zipWithIndex) {
        val slot = backend.lsu.slots(i)
        out.owner := BoringUtils.bore(slot.io.owner)
        out.result := BoringUtils.bore(slot.io.complete.bits)
        out.phase := BoringUtils.bore(slot.io.phase)
        out.start := BoringUtils.bore(slot.io.start.valid) && BoringUtils.bore(slot.io.start.ready)
        out.startForward := BoringUtils.bore(slot.io.start.bits.forward.valid)
        out.request := BoringUtils.bore(slot.io.memory.request.valid) && BoringUtils.bore(slot.io.memory.request.ready)
        out.response := BoringUtils.bore(slot.io.memory.response.valid) && BoringUtils.bore(slot.io.memory.response.ready)
        out.completeValid := BoringUtils.bore(slot.io.complete.valid)
        out.completeReady := BoringUtils.bore(slot.io.complete.ready)
        out.cancelled := BoringUtils.bore(slot.cancelled)
        out.cancel := BoringUtils.bore(slot.io.cancel)
        // Test-only 4 x 7 sideband bits provide the same passive OFF/ON view.
        // They feed only observation outputs; native production totals exclude them.
        val saved = Reg(Valid(UInt(fixtureParams.physBits.W)))
        val starting = BoringUtils.bore(slot.io.start.bits)
        val destination = BoringUtils.bore(backend.lsu.io.issueDestination.get)
        when(out.start) {
            saved.valid := destination.valid && destination.bits =/= 0.U && !starting.store && !starting.atomic
            saved.bits := destination.bits
        }
        out.savedDestination := saved
        if (enabled) {
            out.held := BoringUtils.bore(backend.lsu.io.heldLoadValue.get(i))
            out.publish := BoringUtils.bore(backend.lsu.io.loadResultPublish.get(i))
        } else {
            // Semantic raw-holder observation only, not connected to production readiness.
            out.held.valid := out.completeValid && !out.result.exception && saved.valid
            out.held.bits.destination := saved.bits
            out.held.bits.data := out.result.data
            out.publish := 0.U.asTypeOf(out.publish)
        }
    }
    val rows = Seq(row0, row1, row2, row3, row4, row5, row6, row7, row8, row9, row10, row11, row12, row13, row14, row15)
    for ((out, i) <- rows.zipWithIndex) {
        val entry = BoringUtils.bore(backend.issueEntries(i))
        out.token := entry.renamed.token
        out.source1 := entry.renamed.source1
        out.source2 := entry.renamed.source2
        out.memory := entry.request.memory
        out.store := entry.request.store
        out.mulDiv := entry.request.mulDiv
        out.system := entry.request.system
        out.usePc := entry.request.usePc
        out.useImmediate := entry.request.useImmediate
    }
    val held0 = BoringUtils.bore(backend.executionStages(0).io.deq.bits)
        .asTypeOf(new IntegerExecutionOperands(fixtureParams))
    val held0Occupied = BoringUtils.bore(backend.executionStages(0).io.occupied)
    val held0Ready = BoringUtils.bore(backend.executionStages(0).io.deq.ready)

    for (lane <- 0 until 2) {
        val stage = backend.executionStages(lane)
        val incomingBits = BoringUtils.bore(stage.io.enq.bits)
        val heldBits = BoringUtils.bore(stage.io.deq.bits)
        val incoming = incomingBits.asTypeOf(new IntegerExecutionOperands(fixtureParams))
        val held = heldBits.asTypeOf(new IntegerExecutionOperands(fixtureParams))
        val out = Seq(observation0, observation1)(lane)
        out.occupied := BoringUtils.bore(stage.io.occupied)
        out.cancel := BoringUtils.bore(stage.io.cancel)
        out.enqValid := BoringUtils.bore(stage.io.enq.valid)
        out.enqReady := BoringUtils.bore(stage.io.enq.ready)
        out.deqValid := BoringUtils.bore(stage.io.deq.valid)
        out.deqReady := BoringUtils.bore(stage.io.deq.ready)
        out.heldToken := held.entry.renamed.token
        out.heldDestination := held.entry.renamed.destination
        out.heldForwardable := held.forwardable
        out.heldLeft := held.left
        out.heldRight := held.right
        out.heldResult := results(lane)
        out.heldDestinationReady := physicalReady(Mux(out.occupied, out.heldDestination, 0.U))
        out.promiseValid := promises(lane).valid
        out.promiseDestination := promises(lane).bits
        out.incomingToken := incoming.entry.renamed.token
        out.incomingSource1 := incoming.entry.renamed.source1
        out.incomingSource2 := incoming.entry.renamed.source2
        out.incomingUsePc := incoming.entry.request.usePc
        out.incomingUseImmediate := incoming.entry.request.useImmediate
        out.incomingLeft := incoming.left
        out.incomingRight := incoming.right
        out.incomingMemory := incoming.entry.request.memory
        out.prepared := BoringUtils.bore(backend.prepared(lane))
        val storePayload = backend.earlyStorePayloads.get._2(lane)
        out.storePrepareToken := BoringUtils.bore(storePayload.token)
        out.storePrepareBase := BoringUtils.bore(storePayload.base)
        out.storePrepareImmediate := BoringUtils.bore(storePayload.immediate)
        out.storePrepareData := BoringUtils.bore(storePayload.data)
        out.storePrepareDataReady := BoringUtils.bore(storePayload.dataReady)
        val captures = out.enqValid && out.enqReady
        val heldPromise = held0Occupied && !held0Ready && promises(0).valid
        out.capturedHeld0Mask := Cat(
            captures && heldPromise && !incoming.entry.request.useImmediate &&
                incoming.entry.renamed.source2 === held0.entry.renamed.destination,
            captures && heldPromise && !incoming.entry.request.usePc &&
                incoming.entry.renamed.source1 === held0.entry.renamed.destination)
        val actualCompletion = BoringUtils.bore(backend.ledger.io.complete(lane))
        out.actualCompletionValid := actualCompletion.valid
        out.actualCompletionToken := actualCompletion.bits.token
        out.actualCompletionException := actualCompletion.bits.exception
        out.actualCompletionAccepted := BoringUtils.bore(backend.ledger.io.completionAccepted(lane))
        val write = BoringUtils.bore(backend.physicalWrites.get(lane))
        out.prfWriteValid := write.valid
        out.prfWriteDestination := write.bits.address
        out.prfWriteData := write.bits.data

        // Passive lifecycle checks supplement, rather than replace, the host oracle.
        val heldAcrossEdge = out.occupied && !out.deqReady && !out.cancel
        val wasHeld = RegNext(heldAcrossEdge, false.B)
        val previousHeld = RegEnable(heldBits, heldAcrossEdge)
        when(wasHeld) {
            assert(out.occupied && heldBits === previousHeld,
                "a stalled old execution owner cannot be overwritten")
        }
        val previousIncoming = RegEnable(incomingBits, captures)
        when(RegNext(captures, false.B)) {
            assert(out.occupied && heldBits === previousIncoming,
                "the new owner appears only after its actual capture edge")
        }
        when(captures) {
            assert(!out.incomingMemory, "held ALU promise cannot enqueue memory work")
        }
        if (lane == 0) {
            assert(!out.capturedHeld0Mask.orR,
                "a held non-ready producer cannot lend same-lane replacement credit")
        }
    }
    when(promises(0).valid && promises(1).valid) {
        assert(promises(0).bits =/= promises(1).bits,
            "live non-aliased ALU promises must own distinct physical destinations")
    }
}

object LoadReadyBackendGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)))
    LoadReadyBackendFixture.write(args.head, args(1) == "1")
    ChiselStage.emitCHIRRTLFile(new LoadReadyBackendGsim(args(1) == "1"),
        Array("--target-dir", args.head))
}
