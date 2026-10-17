package ooo
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Actual selected checked adapter. Translation replies and architectural state
  * are explicit environment inputs; no page-table walker or CPU is claimed.
  */
class CollectionReadTranslationGsim(enabled: Boolean) extends Module {
    val profile = CollectionReadProfileV2.config
    val p = profile.coreParams.copy(postedCollectionReadProgress = enabled)
    val adapter = Module(new DataTranslationAdapter(p, entries = 8, registerCheckedRequests = true,
        translationHitFlow = profile.translationHitFlow, usePublishedPmpChanges = p.pmpChangePublicationEnabled,
        registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent, queuedHeadSelection = p.queuedHeadSelection,
        alignedNextLinePmp = p.alignedNextLinePmp, factorCheckedNextAllowed = p.factorCheckedNextAllowed,
        registerNextLineDecision = true))
    val io = IO(new Bundle {
        val virtual = Flipped(new DataPort(p.dataReturnHandleBits))
        val physical = new DataPort(p.dataReturnHandleBits)
        val collectionRead = Input(Bool())
        val physicalCollectionRead = Output(Bool())
        val posted = new PostedStoreTranslationPort(p.postedProofConfig.get)
        val translation = new SvTranslationPort
        val loadPrecheck = Flipped(new VirtualLoadPrecheckPort)
        val translationPeek = new SvTranslationPeekPort
        val precheckFlush = Input(Bool())
        val canonicalStoreOrigin = Input(Valid(new CanonicalStoreOrigin(p)))
        val frozenStoreProof = Input(Valid(new FrozenStoreProof))
        val canonicalStoreCertificate = Output(Valid(new CanonicalStoreCertificate(p)))
        val vmState = Input(new VmCsrState)
        val pmpCfg = Input(Vec(16, UInt(8.W)))
        val pmpAddr = Input(Vec(16, UInt(54.W)))
        val pmpRawChanged = Input(Bool())
        val idle = Output(Bool())
        val physicalRequest = Output(Bool())
        val pageFault = Output(Bool())
        val ingressPass = Output(Bool())
        val identityPass = Output(Bool())
        val ingressQueued = Output(Bool())
        val translatedEnqueue = Output(Bool())
        val translatedDequeue = Output(Bool())
        val checkedEnqueue = Output(Bool())
        val checkedDequeue = Output(Bool())
        val checkedRead = Output(Bool())
        val checkedFault = Output(Bool())
    })
    adapter.io.virtual <> io.virtual
    io.physical <> adapter.io.physical
    adapter.io.upstreamCollectionHeadRead.foreach(_ := io.collectionRead)
    io.physicalCollectionRead := adapter.io.physicalCollectionHeadRead.getOrElse(false.B)
    io.posted <> adapter.io.posted.get
    io.translation <> adapter.io.translation
    adapter.io.loadPrecheck.get <> io.loadPrecheck
    io.translationPeek <> adapter.io.translationPeek.get
    adapter.io.precheckFlush.get := io.precheckFlush
    adapter.io.canonicalStoreOrigin.get := io.canonicalStoreOrigin
    adapter.io.frozenStoreProof.get := io.frozenStoreProof
    io.canonicalStoreCertificate := adapter.io.canonicalStoreCertificate.get
    adapter.io.vmState := io.vmState
    val pmp = Wire(new PmpState)
    pmp.cfg := io.pmpCfg; pmp.addr := io.pmpAddr
    PmpState.decodeRegions(pmp)
    adapter.io.pmpState := pmp
    adapter.io.pmpRawChanged.get := io.pmpRawChanged
    io.idle := adapter.io.idle
    io.physicalRequest := adapter.io.physicalRequest
    io.pageFault := adapter.io.pageFault
    io.ingressPass := BoringUtils.bore(adapter.physicalIngressPass)
    io.identityPass := BoringUtils.bore(adapter.identityPass)
    io.ingressQueued := BoringUtils.bore(adapter.virtualRequests.get.io.enq.valid) && BoringUtils.bore(adapter.virtualRequests.get.io.enq.ready)
    io.translatedEnqueue := BoringUtils.bore(adapter.translated.io.enq.valid) && BoringUtils.bore(adapter.translated.io.enq.ready)
    io.translatedDequeue := BoringUtils.bore(adapter.translated.io.deq.valid) && BoringUtils.bore(adapter.translated.io.deq.ready)
    io.checkedEnqueue := BoringUtils.bore(adapter.checked.get.enq.valid) && BoringUtils.bore(adapter.checked.get.enq.ready)
    io.checkedDequeue := BoringUtils.bore(adapter.checked.get.deq.valid) && BoringUtils.bore(adapter.checked.get.deq.ready)
    io.checkedRead := BoringUtils.bore(adapter.checked.get.deq.valid) &&
        (if (enabled) BoringUtils.bore(adapter.checked.get.deq.bits.collectionHeadRead.get) else false.B)
    io.checkedFault := BoringUtils.bore(adapter.checked.get.deq.valid) && BoringUtils.bore(adapter.checked.get.deq.bits.fault)
    require(adapter.io.virtual.request.bits.getWidth == 184 && adapter.io.physical.request.bits.getWidth == 184)
}
object CollectionReadTranslationGsimMain extends App {
    require(args.length == 3)
    val out = java.nio.file.Path.of(args(0)); java.nio.file.Files.createDirectories(out)
    val p = CollectionReadProfileV2.config.coreParams.copy(postedCollectionReadProgress = args(1).toBoolean)
    val actual = ujson.read(CollectionReadProfileJson.json(p))
    val legacy = ujson.read(ujson.write(actual))
    require(legacy.obj.remove("postedCollectionReadProgress").contains(ujson.Bool(args(1).toBoolean)))
    val expected = ujson.read(java.nio.file.Files.readString(java.nio.file.Path.of(args(2))))
    require(legacy == expected("core"))
    require(ujson.read(CollectionReadProfileJson.json(CollectionReadProfileV2.config)) == expected("profile"))
    require(expected("featureFlags")("registerNextLineDecision") == ujson.Bool(true))
    java.nio.file.Files.writeString(out.resolve("actual-core.json"),ujson.write(actual,indent=2)+"\n")
    java.nio.file.Files.writeString(out.resolve("CollectionReadTranslationGsim.fir"),
        ChiselStage.emitCHIRRTL(new CollectionReadTranslationGsim(args(1).toBoolean)))
}
