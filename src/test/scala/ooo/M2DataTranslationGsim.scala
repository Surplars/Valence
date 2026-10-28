package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._
import soc.platform.CommonA1RebuildProfile

/** Actual FullCandidate or FullM2 DTA + real 16-entry DTLB/single walker.
  * Identical complete core parameters, PMP, hints and service law. This is not
  * a CPU throughput claim; the separate true-tile VM witness covers integration.
  */
class M2DataTranslationGsim(registered: Boolean) extends Module {
    val config = (if (registered) CommonA1RebuildProfile.FullM2 else CommonA1RebuildProfile.FullCandidate).config
    val p = config.coreParams
    require(p.fpEnabled && p.fpConfig.d && p.virtualMemoryLevels == 3 && p.pmpEntries == 16)
    require(p.speculativeRamBase == BigInt("80200000", 16) && p.speculativeRamBytes == BigInt(2).pow(31))
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val physical = new DataPort
        val pte = new SvPteReadPort
        val context = Input(new VmCsrState)
        val pmpCfg = Input(UInt(8.W))
        val pmpAddress = Input(UInt(54.W))
        val flush = Input(Bool())
        val origin = Input(Valid(new CanonicalStoreOrigin(p)))
        val certificate = Output(Valid(new CanonicalStoreCertificate(p)))
        val epoch = Output(UInt(32.W))
        val stable = Output(Bool())
        val translationHit = Output(Bool())
        val translationWalk = Output(Bool())
        // Observation-only events. Permission/address expectations remain in the independent host.
        val hitPass = Output(Bool())
        val hitOffer = Output(Bool())
        val translatedPush = Output(Bool())
        val translatedPop = Output(Bool())
        val translationFire = Output(Bool())
        val checkedPush = Output(Bool())
        val checkedCount = Output(UInt(2.W))
        val translatedCount = Output(UInt(4.W))
        val ownerCount = Output(UInt(4.W))
        val idle = Output(Bool())
    })
    val adapter = Module(new DataTranslationAdapter(p, registerCheckedRequests = true,
        translationHitFlow = config.translationHitFlow,
        queuedHeadSelection = p.queuedHeadSelection, alignedNextLinePmp = p.alignedNextLinePmp))
    val translation = Module(new SvTranslationService(p.virtualMemoryLevels, config.dataTranslationEntries,
        p.pmpEntries, loadPeek = true, writeReadReuse = config.dataTlbWriteReadReuse))
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := io.pmpCfg
    pmp.addr(0) := io.pmpAddress
    PmpState.decodeRegions(pmp)
    adapter.io.vmState := io.context
    adapter.io.pmpState := pmp
    translation.io.pmpState := pmp
    adapter.io.virtual <> io.upstream
    io.physical <> adapter.io.physical
    translation.io.client <> adapter.io.translation
    io.pte <> translation.io.memory
    translation.io.flush := io.flush
    adapter.io.canonicalStoreOrigin.get := io.origin
    io.certificate := adapter.io.canonicalStoreCertificate.get
    adapter.io.precheckFlush.get := io.flush
    adapter.io.loadPrecheck.get.request.valid := false.B
    adapter.io.loadPrecheck.get.request.bits := 0.U.asTypeOf(adapter.io.loadPrecheck.get.request.bits)
    translation.io.loadPeek.get <> adapter.io.translationPeek.get
    io.epoch := adapter.io.loadPrecheck.get.epoch
    io.stable := adapter.io.loadPrecheck.get.stable
    io.translationHit := translation.io.tlbHit
    io.translationWalk := translation.io.walkStart
    io.hitPass := BoringUtils.bore(adapter.translationHitPass)
    io.hitOffer := (if (config.translationHitFlow) BoringUtils.bore(adapter.translationHitOffer) else false.B)
    io.translatedPush := BoringUtils.bore(adapter.translated.io.enq.valid) &&
        BoringUtils.bore(adapter.translated.io.enq.ready)
    io.translatedPop := BoringUtils.bore(adapter.translated.io.deq.valid) &&
        BoringUtils.bore(adapter.translated.io.deq.ready)
    io.translationFire := adapter.io.translation.request.fire
    io.checkedPush := BoringUtils.bore(adapter.checked.get.enq.valid) &&
        BoringUtils.bore(adapter.checked.get.enq.ready)
    io.checkedCount := BoringUtils.bore(adapter.checked.get.count)
    io.translatedCount := BoringUtils.bore(adapter.translated.io.count)
    io.ownerCount := BoringUtils.bore(adapter.owners.io.count)
    io.idle := adapter.io.idle && translation.io.idle
}

object M2DataTranslationGsimMain extends App {
    require(args.length == 2 && Set("baseline", "registered").contains(args(1)),
        "output-directory baseline|registered")
    ChiselStage.emitCHIRRTLFile(new M2DataTranslationGsim(args(1) == "registered"),
        Array("--target-dir", args.head))
}
