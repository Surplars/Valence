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
class CombinedCheckedFlowCpuGsim extends CommonA1VmPipelineGsim("full-r1-m3-checked-flow") {
    override def desiredName: String = "CommonA1VmPipelineGsim"
    private val params = CommonA1RebuildProfile.named("full-r1-m3-checked-flow").config.coreParams
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
        CommonA1RebuildProfile.named("full-r1-m3-checked-flow").config.translationHitFlow)
    val flow = IO(new Bundle {
        val enabled = Output(Bool())
        val requestSlots = Output(UInt(4.W))
        val precheckedPass = Output(Bool())
        val rawPass = Output(Bool())
    })
    private val backend = tile.core.core.core.backend
    private val lsu = backend.lsu
    private def observe[T <: Data](value: T): T = BoringUtils.bore(value)
    private def m3Fire(port: DecoupledIO[_]): Bool = observe(port.valid) && observe(port.ready)
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

object CombinedCheckedFlowCpuGsimMain extends App {
    require(args.length == 1, "output-directory")
    val config = CommonA1RebuildProfile.named("full-r1-m3-checked-flow").config
    val out = Paths.get(args(0))
    Files.createDirectories(out)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-config.json"), config)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-parameters.json"), config.coreParams)
    Files.writeString(out.resolve("scope.txt"),
        "Actual full-r1-m3-checked-flow CommonA1 tile; two unchanged VM guests, passive full-token DTA stage observer. No PPA/board claim.\n")
    ChiselStage.emitCHIRRTLFile(new CombinedCheckedFlowCpuGsim, Array("--target-dir", args.head))
}
