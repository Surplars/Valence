package soc.core.ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import java.nio.file.{Files, Paths}
import soc.platform.CommonA1RebuildProfile

/** One additional actual-tile candidate, inheriting the immutable M2/R1 bus
  * fixture. All new signals are passive test observations, not production
  * counters or permissions. The old wrapper and its emitted model remain intact.
  */
class PreparedHeadStoreCpuGsim extends CommonA1VmPipelineGsim("full-r1-m3-checked-flow-store-row") {
    override def desiredName: String = "CommonA1VmPipelineGsim"
    private val params = CommonA1RebuildProfile.named("full-r1-m3-checked-flow-store-row").config.coreParams
    require(params.completedCanonicalStoreForwarding && params.circularFetchPayload)
    require(!params.registeredDataTranslation && params.memoryEntries == 4)
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
    require(params.combinedCheckedDataFlow && params.precheckedDataRequestFlow &&
        CommonA1RebuildProfile.named("full-r1-m3-checked-flow-store-row").config.translationHitFlow)
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
    flow.enabled := params.combinedCheckedDataFlow.B
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
}

object PreparedHeadStoreCpuGsimMain extends App {
    require(args.length == 1, "output-directory")
    val config = CommonA1RebuildProfile.named("full-r1-m3-checked-flow-store-row").config
    val out = Paths.get(args(0))
    Files.createDirectories(out)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-config.json"), config)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-parameters.json"), config.coreParams)
    Files.writeString(out.resolve("scope.txt"),
        "Actual full-r1-m3-checked-flow-store-row CommonA1 tile; two unchanged VM guests, passive full-token row/actual LSU source/DTA stage observers. No PPA/board claim.\n")
    ChiselStage.emitCHIRRTLFile(new PreparedHeadStoreCpuGsim, Array("--target-dir", args.head))
}
