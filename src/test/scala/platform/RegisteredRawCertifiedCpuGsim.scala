package soc.core.ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import java.nio.file.{Files, Paths}
import soc.platform.CommonA1RebuildProfile

/** Matched fresh control and registered-raw candidate with the same passive
  * observation surface. The immutable original bus wrapper, guest programs and
  * load host are retained. No test signal grants authority or changes scheduling.
  */
class RegisteredRawCertifiedCpuGsim(profile: String, sideEffectFreeFetchRanges: Seq[SideEffectFreeFetchRange] = Seq.empty) extends CommonA1VmPipelineGsim(profile, sideEffectFreeFetchRanges) {
    override def desiredName: String = "CommonA1VmPipelineGsim"
    private val selectedConfig = CommonA1RebuildProfile.named(profile).config
    private val params = selectedConfig.coreParams
    require(params.completedCanonicalStoreForwarding && params.circularFetchPayload)
    require(params.memoryEntries == 4)
    require(params.registeredDataTranslation == params.registeredRawCertifiedFlow)
    require(selectedConfig.translationHitFlow == !params.registeredRawCertifiedFlow)
    require(params.combinedCheckedDataFlow == !params.registeredRawCertifiedFlow)
    val m3 = IO(new Bundle {
        val enabled = Output(Bool())
        val start = Output(Valid(new MemoryOperation(params)))
        val complete = Output(Valid(new BackendCompletion(params)))
        val sourceStore = Output(Valid(new StoreForward(params)))
        val forwarded = Output(Bool())
        val startSlots = Output(UInt(4.W))
        val completeSlots = Output(UInt(4.W))
        val certificate = Output(Valid(new CanonicalStoreCertificate(params)))
        val epoch = Output(UInt(32.W))
        val stable = Output(Bool())
    })
    require(params.precheckedDataRequestFlow)
    val flow = IO(new Bundle {
        val enabled = Output(Bool())
        val requestSlots = Output(UInt(4.W))
        val precheckedPass = Output(Bool())
        val rawPass = Output(Bool())
    })
    require(params.preparedHeadStoreOperands)
    val row = IO(new Bundle {
        val enabled = Output(Bool())
        val candidate = Output(Valid(new PreparedHeadStorePayload(params)))
        val prepared = Output(Valid(new PreparedHeadStorePayload(params)))
        val consume = Output(Valid(new RobToken(params)))
        val ownerLive = Output(Bool())
        val atHead = Output(Bool())
        val flush = Output(Bool())
        val choice = Output(Bool())
        val eligible = Output(Bool())
        val normalIssued = Output(Bool())
        val normalIssue = Output(new PreparedStoreIssue(params))
        val startParallel = Output(Bool())
        val startDestination = Output(Valid(UInt(params.physBits.W)))
        val head = Output(Valid(new RobToken(params)))
    })
    private val backend = tile.core.core.core.backend
    private val lsu = backend.lsu
    private def observe[T <: Data](value: T): T = BoringUtils.bore(value)
    private def m3Fire(port: DecoupledIO[_]): Bool = observe(port.valid) && observe(port.ready)
    private val preparedRow = backend.preparedHeadStore.get
    row.enabled := params.preparedHeadStoreOperands.B
    row.candidate := observe(preparedRow.io.candidate)
    row.prepared := observe(preparedRow.io.prepared)
    row.consume := observe(preparedRow.io.consume)
    row.ownerLive := observe(preparedRow.io.ownerLive)
    row.atHead := observe(preparedRow.io.atHead)
    row.flush := observe(preparedRow.io.flush)
    row.choice := observe(backend.preparedStoreChoice.get)
    row.eligible := observe(backend.preparedStoreEligible.get)
    row.normalIssued := observe(backend.normalMemoryIssued)
    row.normalIssue := observe(backend.normalStoreIssue.get)
    row.startParallel := observe(lsu.io.parallel)
    row.startDestination := observe(lsu.io.issueDestination.get)
    row.head.valid := observe(backend.ledger.io.headValid)
    row.head.bits := observe(backend.headRenamed.token)
    flow.enabled := (params.precheckedDataRequestFlow &&
        (params.combinedCheckedDataFlow || params.registeredRawCertifiedFlow)).B
    flow.requestSlots := VecInit(lsu.slots.map(slot => m3Fire(slot.io.memory.request))).asUInt
    flow.precheckedPass := observe(adapter.precheckedPass)
    flow.rawPass := observe(adapter.translationHitPass)
    m3.enabled := params.completedCanonicalStoreForwarding.B
    m3.start.valid := m3Fire(lsu.io.start)
    m3.start.bits := observe(lsu.io.start.bits)
    m3.complete.valid := m3Fire(lsu.io.complete)
    m3.complete.bits := observe(lsu.io.complete.bits)
    m3.sourceStore := observe(lsu.io.forwardStore)
    m3.forwarded := observe(lsu.io.forwarded)
    m3.startSlots := VecInit(lsu.slots.map(slot => m3Fire(slot.io.start))).asUInt
    m3.completeSlots := VecInit(lsu.slots.map(slot => m3Fire(slot.io.complete))).asUInt
    m3.certificate := observe(backend.canonicalStoreTracker.get.io.certificate)
    m3.epoch := observe(backend.io.loadPrecheck.get.epoch)
    m3.stable := observe(backend.io.loadPrecheck.get.stable)
    require(params.elasticLoadProofSupply)
    // Stable test-only names replace fragile backend-generated temporary names.
    val supply = IO(new Bundle {
        val offer = Output(Bool())
        val ready = Output(Bool())
        val choice = Output(Bool())
        val staged = Output(Bool())
        val states = Output(UInt(8.W))
        val cancelled = Output(UInt(4.W))
        val owner0 = Output(new RobToken(params))
        val owner1 = Output(new RobToken(params))
        val owner2 = Output(new RobToken(params))
        val owner3 = Output(new RobToken(params))
    })
    supply.offer := observe(lsu.io.start.valid)
    supply.ready := observe(lsu.io.start.ready)
    supply.choice := observe(backend.memoryChoice.valid)
    supply.staged := observe(backend.stagedMemoryValid.get)
    supply.states := VecInit(lsu.slots.map(slot => observe(slot.state))).asUInt
    supply.cancelled := VecInit(lsu.slots.zipWithIndex.map { case (slot, index) =>
        observe(slot.cancelled) || observe(lsu.io.cancel(index))
    }).asUInt
    supply.owner0 := observe(lsu.slots(0).operation.token)
    supply.owner1 := observe(lsu.slots(1).operation.token)
    supply.owner2 := observe(lsu.slots(2).operation.token)
    supply.owner3 := observe(lsu.slots(3).operation.token)
    val proof = IO(new Bundle {
        val current = Output(Valid(new VirtualRamLoadCandidate(params)))
        val lookahead = Output(Valid(new VirtualRamLoadCandidate(params)))
        val descriptorOwner = Output(Valid(new ElasticVirtualRamLoadOwner(params)))
        val translatedOwner = Output(Valid(new ElasticVirtualRamLoadOwner(params)))
        val preparedOwner = Output(Valid(new ElasticVirtualRamLoadOwner(params)))
        val prepared = Output(Valid(new VirtualRamLoadCertificate(params)))
        val live = Output(UInt(3.W))
        val epoch = Output(UInt(32.W))
        val stable = Output(Bool())
        val flush = Output(Bool())
        val queryAccept = Output(Bool())
        val queryOffer = Output(Bool())
        val queryFromDescriptor = Output(Bool())
        val translatedAdvance = Output(Bool())
        val descriptorCapture = Output(Bool())
        val descriptorTransfer = Output(Bool())
        val descriptorPreempt = Output(Bool())
        val translatedPreempt = Output(Bool())
        val preparedPreempt = Output(Bool())
        val negativeExpire = Output(Bool())
        val hit = Output(Bool())
    })
    if (!params.bufferedThirdRankLoadProof) {
        val elastic = backend.elasticLoadPreparation.get
        proof.current := observe(elastic.io.current)
        proof.lookahead := observe(elastic.io.lookahead)
        proof.descriptorOwner := observe(elastic.io.descriptorOwner)
        proof.translatedOwner := observe(elastic.io.translatedOwner)
        proof.preparedOwner := observe(elastic.io.preparedOwner)
        proof.prepared := observe(elastic.io.prepared)
        proof.live := Cat(observe(elastic.io.preparedOwnerLive), observe(elastic.io.translatedOwnerLive),
            observe(elastic.io.descriptorOwnerLive))
        proof.epoch := observe(elastic.io.precheck.epoch)
        proof.stable := observe(elastic.io.precheck.stable)
        proof.flush := observe(elastic.io.flush)
        proof.queryAccept := observe(elastic.queryAccept)
        proof.queryOffer := observe(elastic.queryOffer)
        proof.queryFromDescriptor := observe(elastic.queryFromDescriptor)
        proof.translatedAdvance := observe(elastic.translatedAdvance)
        proof.descriptorCapture := observe(elastic.descriptorCapture)
        proof.descriptorTransfer := observe(elastic.descriptorTransfer)
        proof.descriptorPreempt := false.B
        proof.translatedPreempt := observe(elastic.translatedPreempt)
        proof.preparedPreempt := observe(elastic.preparedPreempt)
        proof.negativeExpire := observe(elastic.negativeExpire)
        proof.hit := observe(elastic.io.hit)
    } else {
        val elastic = backend.bufferedLoadPreparation.get
        val descriptors = VecInit((0 until 2).map(i => observe(elastic.io.descriptorOwner(i))))
        val results = VecInit((0 until 2).map(i => observe(elastic.io.preparedOwner(i))))
        val descriptorLive = VecInit((0 until 2).map(i => observe(elastic.io.descriptorOwnerLive(i))))
        val resultLive = VecInit((0 until 2).map(i => observe(elastic.io.preparedOwnerLive(i))))
        val queryIndex = observe(elastic.queryDescriptorIndex)
        val resultIndex = observe(elastic.selectedPreparedIndex)
        proof.current := observe(elastic.io.current)
        proof.lookahead := observe(elastic.io.lookahead(0))
        // Preserve the immutable query-provenance host ABI, not an arbitrary row0 projection.
        proof.descriptorOwner := descriptors(queryIndex)
        proof.translatedOwner := observe(elastic.io.translatedOwner)
        proof.preparedOwner := results(resultIndex)
        proof.prepared := observe(elastic.io.prepared)
        proof.live := Cat(resultLive(resultIndex), observe(elastic.io.translatedOwnerLive), descriptorLive(queryIndex))
        proof.epoch := observe(elastic.io.precheck.epoch)
        proof.stable := observe(elastic.io.precheck.stable)
        proof.flush := observe(elastic.io.flush)
        proof.queryAccept := observe(elastic.queryAccept)
        proof.queryOffer := observe(elastic.queryOffer)
        proof.queryFromDescriptor := observe(elastic.queryFromDescriptor)
        proof.translatedAdvance := observe(elastic.translatedAdvance)
        proof.descriptorCapture := observe(elastic.descriptorCapture)
        proof.descriptorTransfer := observe(elastic.descriptorTransfer)
        proof.descriptorPreempt := false.B
        proof.translatedPreempt := false.B
        proof.preparedPreempt := observe(elastic.preparedPreempt)
        proof.negativeExpire := observe(elastic.negativeExpire)
        proof.hit := observe(elastic.io.hit)
    }
    // Candidate-only passive evidence. Scalar rows/events avoid the simulator's
    // vector accessor ABI, and untapped exports contain none of these ports.
    val bufferedProof = if (params.bufferedThirdRankLoadProof) Some(IO(new Bundle {
        val descriptor0 = Output(Valid(new ElasticVirtualRamLoadOwner(params)))
        val descriptor1 = Output(Valid(new ElasticVirtualRamLoadOwner(params)))
        val translated = Output(Valid(new ElasticVirtualRamLoadOwner(params)))
        val prepared0 = Output(Valid(new ElasticVirtualRamLoadOwner(params)))
        val prepared1 = Output(Valid(new ElasticVirtualRamLoadOwner(params)))
        val live = Output(UInt(5.W))
        val occupancy = Output(UInt(3.W))
        val lookaheadThird = Output(Valid(new VirtualRamLoadCandidate(params)))
        val descriptorCapture = Output(Bool())
        val descriptorCaptureIndex = Output(UInt(1.W))
        val captureLookaheadIndex = Output(UInt(1.W))
        val allocation0 = Output(Valid(new RenamedInstruction(params)))
        val allocation1 = Output(Valid(new RenamedInstruction(params)))
        val allocationImmediate0 = Output(UInt(64.W))
        val allocationImmediate1 = Output(UInt(64.W))
        val allocationSize0 = Output(UInt(2.W))
        val allocationSize1 = Output(UInt(2.W))
        val allocationOrdinary0 = Output(Bool())
        val allocationOrdinary1 = Output(Bool())
        val write0 = Output(Valid(new Bundle { val address = UInt(params.physBits.W); val data = UInt(64.W) }))
        val write1 = Output(Valid(new Bundle { val address = UInt(params.physBits.W); val data = UInt(64.W) }))
        val reserve0 = Output(Valid(UInt(params.physBits.W)))
        val reserve1 = Output(Valid(UInt(params.physBits.W)))
        val wake0 = Output(Valid(UInt(params.physBits.W)))
        val wake1 = Output(Valid(UInt(params.physBits.W)))
        val wake2 = Output(Valid(UInt(params.physBits.W)))
        val pending = Output(UInt(params.robEntries.W))
        val memoryLive = Output(UInt(params.robEntries.W))
        val killed = Output(UInt(params.robEntries.W))
        val ready = Output(UInt(params.physicalRegs.W))
    })) else None
    bufferedProof.foreach { observation =>
        val elastic = backend.bufferedLoadPreparation.get
        observation.descriptor0 := observe(elastic.io.descriptorOwner(0))
        observation.descriptor1 := observe(elastic.io.descriptorOwner(1))
        observation.translated := observe(elastic.io.translatedOwner)
        observation.prepared0 := observe(elastic.io.preparedOwner(0))
        observation.prepared1 := observe(elastic.io.preparedOwner(1))
        observation.live := Cat(observe(elastic.io.preparedOwnerLive(1)), observe(elastic.io.preparedOwnerLive(0)),
            observe(elastic.io.translatedOwnerLive), observe(elastic.io.descriptorOwnerLive(1)),
            observe(elastic.io.descriptorOwnerLive(0)))
        observation.occupancy := PopCount(Seq(observation.descriptor0.valid, observation.descriptor1.valid,
            observation.translated.valid, observation.prepared0.valid, observation.prepared1.valid))
        observation.lookaheadThird := observe(elastic.io.lookahead(1))
        observation.descriptorCapture := observe(elastic.descriptorCapture)
        observation.descriptorCaptureIndex := observe(elastic.descriptorCaptureIndex)
        observation.captureLookaheadIndex := observe(elastic.captureLookaheadIndex)
        observation.allocation0 := observe(backend.ledger.io.renamed(0))
        observation.allocation1 := observe(backend.ledger.io.renamed(1))
        observation.allocationImmediate0 := observe(backend.io.allocate(0).bits.immediate)
        observation.allocationImmediate1 := observe(backend.io.allocate(1).bits.immediate)
        observation.allocationSize0 := observe(backend.io.allocate(0).bits.memorySize)
        observation.allocationSize1 := observe(backend.io.allocate(1).bits.memorySize)
        def ordinary(lane: Int): Bool = {
            val request = backend.io.allocate(lane).bits
            observe(request.memory) && !observe(request.store) && !observe(request.atomic) &&
                !observe(request.system) && !observe(request.mulDiv) && !observe(request.fetchFault) &&
                !observe(request.fetchPageFault) && observe(request.operation) === IntegerOp.add &&
                observe(request.controlFlow) === ControlFlow.none
        }
        observation.allocationOrdinary0 := ordinary(0)
        observation.allocationOrdinary1 := ordinary(1)
        observation.write0 := observe(backend.physicalWrites.get(0))
        observation.write1 := observe(backend.physicalWrites.get(1))
        observation.reserve0 := observe(backend.readyUpdate.get.io.reserve(0))
        observation.reserve1 := observe(backend.readyUpdate.get.io.reserve(1))
        observation.wake0 := observe(backend.readyUpdate.get.io.wake(0))
        observation.wake1 := observe(backend.readyUpdate.get.io.wake(1))
        observation.wake2 := observe(backend.readyUpdate.get.io.wake(2))
        observation.pending := VecInit(backend.pending.map(value => observe(value))).asUInt
        observation.memoryLive := VecInit(backend.memoryLive.map(value => observe(value))).asUInt
        observation.killed := VecInit(backend.killed.map(value => observe(value))).asUInt
        observation.ready := VecInit(backend.ready.map(value => observe(value))).asUInt
    }

    // Strictly candidate-only: disabled FIR must remain identical to 7daf119,
    // except source locations. No observed value feeds a functional input.
    val returnFlow = if (params.bufferedReturnFlow) Some(IO(new Bundle {
        val rawIndices = Output(UInt(64.W))
        val viewIndices = Output(UInt(64.W))
        val inputValid = Output(Bool())
        val inputReady = Output(Bool())
        val inputBits = Output(new DataResponse)
        val outputValid = Output(Bool())
        val outputReady = Output(Bool())
        val outputBits = Output(new DataResponse)
        val occupancy = Output(UInt(2.W))
        val adapterIdle = Output(Bool())
        val backendIdle = Output(Bool())
        val fpEpoch = Output(Bool())
        val integerBusy = Output(Bool())
        val resultCaptures = Output(UInt(4.W))
    })) else None
    returnFlow.foreach { observation =>
        require(params.reconstructIssueTokenIndex && params.robEntries == 16 && params.tagBits == 64)
        val responses = tile.core.observationResponses.get
        observation.rawIndices := VecInit(backend.queue.map(entry => observe(entry.renamed.token.index))).asUInt
        observation.viewIndices := VecInit(backend.issueEntries.map(entry => observe(entry.renamed.token.index))).asUInt
        observation.inputValid := observe(responses.io.downstream.response.valid)
        observation.inputReady := observe(responses.io.downstream.response.ready)
        observation.inputBits := observe(responses.io.downstream.response.bits)
        observation.outputValid := observe(responses.io.upstream.response.valid)
        observation.outputReady := observe(responses.io.upstream.response.ready)
        observation.outputBits := observe(responses.io.upstream.response.bits)
        observation.occupancy := observe(responses.responses.count)
        observation.adapterIdle := observe(adapter.io.idle)
        observation.backendIdle := observe(backend.io.ownersIdle)
        observation.fpEpoch := observe(backend.fpMemoryEpoch)
        observation.integerBusy := observe(backend.integerMemoryBusy)
        observation.resultCaptures := VecInit(lsu.slots.map(slot => m3Fire(slot.io.memory.response))).asUInt
    }

}

object RegisteredRawCertifiedCpuGsimMain extends App {
    require(args.length == 2, "output-directory exact-profile")
    require(Set("full-r1-m3-checked-flow-store-row-elastic-proof", "full-r1-m3-checked-flow-store-row-elastic-proof-registered-raw").contains(args(1)))
    val config = CommonA1RebuildProfile.named(args(1)).config
    val out = Paths.get(args(0))
    Files.createDirectories(out)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-config.json"), config)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-parameters.json"), config.coreParams)
    Files.writeString(out.resolve("scope.txt"),
        "Actual full-resource CommonA1 tile, fresh same-tool control/candidate; immutable VM and independent-load guests. No PPA/board claim. Profile=" + args(1) + "\n")
    ChiselStage.emitCHIRRTLFile(new RegisteredRawCertifiedCpuGsim(args(1)), Array("--target-dir", args(0)))
}
