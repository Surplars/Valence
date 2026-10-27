package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._
import soc.platform.CommonA1RebuildProfile

/** Matched actual A1 R1/M3 DTA, 16-entry DTLB and real Sv39 walker.
  * Only the explicit combined checked-flow experiment differs. Observations below
  * are passive events/payloads, never expected permission, PA or owner verdicts.
  */
class CombinedCheckedDataFlowGsim(combined: Boolean) extends Module {
    val config = CommonA1RebuildProfile.named(
        if (combined) "full-r1-m3-checked-flow" else "full-r1-m3").config
    val p = config.coreParams
    require(p.fpEnabled && p.fpConfig.d && p.virtualMemoryLevels == 3 && p.pmpEntries == 16)
    require(config.dataTranslationEntries == 16 && p.memoryEntries == 4 && p.dataReturnHandleBits == 0)
    require(config.translationHitFlow && p.precheckedDataRequestFlow == combined)
    require(p.combinedCheckedDataFlow == combined && !p.registeredDataTranslation)
    require(p.canonicalVirtualStoreOverlap && !p.registeredCanonicalStoreEvent)
    require(p.dataNextLinePrefetch && !p.dataStoreNextLinePrefetch)
    require(p.speculativeRamBase == BigInt("80200000", 16) && p.speculativeRamBytes == BigInt(2).pow(31))
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val physical = new DataPort
        val pte = new SvPteReadPort
        val context = Input(new VmCsrState)
        // Scalar entry zero plus explicitly zeroed remaining entries avoids the
        // GSIM top-level Vec-port ABI issue without changing the 16-entry PMP.
        val pmpCfg = Input(UInt(8.W))
        val pmpAddress = Input(UInt(54.W))
        val flush = Input(Bool())
        val origin = Input(Valid(new CanonicalStoreOrigin(p)))
        val certificate = Output(Valid(new CanonicalStoreCertificate(p)))
        val epoch = Output(UInt(32.W))
        val stable = Output(Bool())
        val translationHit = Output(Bool())
        val translationWalk = Output(Bool())
        val incomingFire = Output(Bool())
        val incomingAddress = Output(UInt(64.W))
        val incomingData = Output(UInt(64.W))
        val hitPass = Output(Bool())
        val hitOffer = Output(Bool())
        val precheckedPass = Output(Bool())
        val precheckedOffer = Output(Bool())
        val translationFire = Output(Bool())
        val translationReply = Output(Bool())
        val translatedPush = Output(Bool())
        val translatedPop = Output(Bool())
        val translatedAddress = Output(UInt(64.W))
        val translatedData = Output(UInt(64.W))
        val checkedPush = Output(Bool())
        val checkedPop = Output(Bool())
        val checkedAddress = Output(UInt(64.W))
        val checkedData = Output(UInt(64.W))
        val checkedFault = Output(Bool())
        val checkedPageFault = Output(Bool())
        val ownerPush = Output(Bool())
        val ownerPop = Output(Bool())
        val ownerFault = Output(Bool())
        val ownerPageFault = Output(Bool())
        val checkedCount = Output(UInt(2.W))
        val translatedCount = Output(UInt(4.W))
        val ownerCount = Output(UInt(4.W))
        val idle = Output(Bool())
    })
    val adapter = Module(new DataTranslationAdapter(p, registerCheckedRequests = true,
        translationHitFlow = config.translationHitFlow, registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent,
        queuedHeadSelection = p.queuedHeadSelection, alignedNextLinePmp = p.alignedNextLinePmp,
        factorCheckedNextAllowed = p.factorCheckedNextAllowed))
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
    io.incomingFire := BoringUtils.bore(adapter.incoming.valid) && BoringUtils.bore(adapter.incoming.ready)
    io.incomingAddress := BoringUtils.bore(adapter.incoming.bits.address)
    io.incomingData := BoringUtils.bore(adapter.incoming.bits.data)
    io.hitPass := BoringUtils.bore(adapter.translationHitPass)
    io.hitOffer := BoringUtils.bore(adapter.translationHitOffer)
    io.precheckedPass := BoringUtils.bore(adapter.precheckedPass)
    io.precheckedOffer := (if (combined) BoringUtils.bore(adapter.precheckedOffer) else false.B)
    io.translationFire := adapter.io.translation.request.fire
    io.translationReply := adapter.io.translation.response.fire
    io.translatedPush := BoringUtils.bore(adapter.translated.io.enq.valid) &&
        BoringUtils.bore(adapter.translated.io.enq.ready)
    io.translatedPop := BoringUtils.bore(adapter.translated.io.deq.valid) &&
        BoringUtils.bore(adapter.translated.io.deq.ready)
    io.translatedAddress := BoringUtils.bore(adapter.translated.io.enq.bits.request.address)
    io.translatedData := BoringUtils.bore(adapter.translated.io.enq.bits.request.data)
    io.checkedPush := BoringUtils.bore(adapter.checked.get.enq.valid) &&
        BoringUtils.bore(adapter.checked.get.enq.ready)
    io.checkedPop := BoringUtils.bore(adapter.checked.get.deq.valid) &&
        BoringUtils.bore(adapter.checked.get.deq.ready)
    io.checkedAddress := BoringUtils.bore(adapter.checked.get.enq.bits.request.address)
    io.checkedData := BoringUtils.bore(adapter.checked.get.enq.bits.request.data)
    io.checkedFault := BoringUtils.bore(adapter.checked.get.enq.bits.fault)
    io.checkedPageFault := BoringUtils.bore(adapter.checked.get.enq.bits.pageFault)
    io.ownerPush := BoringUtils.bore(adapter.owners.io.enq.valid) &&
        BoringUtils.bore(adapter.owners.io.enq.ready)
    io.ownerPop := BoringUtils.bore(adapter.owners.io.deq.valid) &&
        BoringUtils.bore(adapter.owners.io.deq.ready)
    io.ownerFault := BoringUtils.bore(adapter.owners.io.enq.bits.fault)
    io.ownerPageFault := BoringUtils.bore(adapter.owners.io.enq.bits.pageFault)
    io.checkedCount := BoringUtils.bore(adapter.checked.get.count)
    io.translatedCount := BoringUtils.bore(adapter.translated.io.count)
    io.ownerCount := BoringUtils.bore(adapter.owners.io.count)
    io.idle := adapter.io.idle && translation.io.idle
}

object CombinedCheckedDataFlowGsimMain extends App {
    require(args.length == 2 && Set("baseline", "combined").contains(args(1)),
        "output-directory baseline|combined")
    ChiselStage.emitCHIRRTLFile(new CombinedCheckedDataFlowGsim(args(1) == "combined"),
        Array("--target-dir", args.head))
}
