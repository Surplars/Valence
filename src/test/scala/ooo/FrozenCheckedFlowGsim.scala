package soc.core.ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import ooo.PendingStoreProofFixture

/** Actual adapter fixture; all taps are passive. Host truth is the original request ledger. */
class FrozenCheckedFlowGsim(enabled: Boolean, queuedHead: Boolean) extends Module {
    val p = PendingStoreProofFixture.params(enabled = true).copy(
        speculativeRamBase = BigInt("180010000", 16), registeredCanonicalStoreEvent = true,
        frozenStoreCheckedFlow = enabled, taggedStoreReturns = true, registeredStoreResponseOwners = true,
        storeBufferEntries = 8, dataNextLinePrefetch = true, dataStoreNextLinePrefetch = true)
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort(p.dataReturnHandleBits))
        val origin = Input(Valid(new CanonicalStoreOrigin(p)))
        val frozen = Input(Valid(new FrozenStoreProof))
        val physical = new DataPort(p.dataReturnHandleBits)
        val translation = new SvTranslationPort
        val context = Input(new VmCsrState)
        val pmpCfg = Input(UInt(8.W))
        val flush = Input(Bool())
        val fastHit = Input(Bool())
        val epoch = Output(UInt(32.W))
        val stable = Output(Bool())
        val checked = Output(Valid(new CanonicalStoreCertificate(p)))
        val idle = Output(Bool())
        val flowEnabled = Output(Bool())
        val incomingFire = Output(Bool())
        val incomingAddress = Output(UInt(64.W))
        val incomingFrozen = Output(Bool())
        val offer = Output(Bool())
        val pass = Output(Bool())
        val translatedPush = Output(Bool())
        val translatedPop = Output(Bool())
        val translatedValid = Output(Bool())
        val translatedReady = Output(Bool())
        val checkedFire = Output(Bool())
        val checkedPop = Output(Bool())
        val checkedHandle = Output(UInt(p.dataReturnHandleBits.W))
        val checkedReady = Output(Bool())
        val checkedFault = Output(Bool())
        val checkedAddress = Output(UInt(64.W))
        val checkedData = Output(UInt(64.W))
        val checkedSize = Output(UInt(3.W))
        val checkedMask = Output(UInt(8.W))
        val checkedWrite = Output(Bool())
        val checkedFrozen = Output(Bool())
        val checkedOrigin = Output(Valid(new CanonicalStoreOrigin(p)))
        val checkedVa = Output(UInt(64.W))
    })
    val dut = Module(new DataTranslationAdapter(p, registerCheckedRequests = true,
        translationHitFlow = true, registerCanonicalStoreEvent = true, queuedHeadSelection = queuedHead,
        alignedNextLinePmp = true))
    dut.io.virtual <> io.upstream
    dut.io.physical <> io.physical
    io.translation.request.valid := dut.io.translation.request.valid
    io.translation.request.bits := dut.io.translation.request.bits
    dut.io.translation.request.ready := io.translation.request.ready
    io.translation.response.ready := dut.io.translation.response.ready
    dut.io.translation.response.valid := Mux(io.fastHit, dut.io.translation.request.valid && dut.io.translation.request.ready,
        io.translation.response.valid)
    dut.io.translation.response.bits := io.translation.response.bits
    when(io.fastHit) {
        dut.io.translation.response.bits := 0.U.asTypeOf(dut.io.translation.response.bits)
        dut.io.translation.response.bits.physicalAddress :=
            p.speculativeRamBase.U(64.W) | dut.io.translation.request.bits.virtualAddress(11, 0)
    }
    dut.io.canonicalStoreOrigin.get := io.origin
    dut.io.frozenStoreProof.get := io.frozen
    dut.io.vmState := io.context
    dut.io.pmpState := PendingStoreProofFixture.pmp(io.pmpCfg, ((BigInt(1) << 54) - 1).U(54.W))
    dut.io.precheckFlush.get := io.flush
    dut.io.loadPrecheck.get.request := 0.U.asTypeOf(dut.io.loadPrecheck.get.request)
    dut.io.translationPeek.get.response := 0.U.asTypeOf(dut.io.translationPeek.get.response)
    io.epoch := dut.io.loadPrecheck.get.epoch
    io.stable := dut.io.loadPrecheck.get.stable
    io.checked := dut.io.canonicalStoreCertificate.get
    io.idle := dut.io.idle
    io.flowEnabled := enabled.B
    io.incomingFire := (BoringUtils.bore(dut.incoming.valid) && BoringUtils.bore(dut.incoming.ready))
    io.incomingAddress := BoringUtils.bore(dut.incoming.bits.address)
    io.incomingFrozen := BoringUtils.bore(dut.frozenPresent)
    io.offer := (if (enabled) BoringUtils.bore(dut.frozenCheckedOffer) else false.B)
    io.pass := BoringUtils.bore(dut.frozenCheckedPass)
    io.translatedPush := (BoringUtils.bore(dut.translated.io.enq.valid) && BoringUtils.bore(dut.translated.io.enq.ready))
    io.translatedPop := (BoringUtils.bore(dut.translated.io.deq.valid) && BoringUtils.bore(dut.translated.io.deq.ready))
    io.translatedValid := BoringUtils.bore(dut.translated.io.deq.valid)
    io.translatedReady := BoringUtils.bore(dut.translated.io.enq.ready)
    io.checkedFire := (BoringUtils.bore(dut.checked.get.enq.valid) && BoringUtils.bore(dut.checked.get.enq.ready))
    io.checkedPop := (BoringUtils.bore(dut.checked.get.deq.valid) && BoringUtils.bore(dut.checked.get.deq.ready))
    io.checkedHandle := BoringUtils.bore(dut.checked.get.enq.bits.request.returnHandle.get)
    io.checkedReady := BoringUtils.bore(dut.checked.get.enq.ready)
    io.checkedFault := BoringUtils.bore(dut.checked.get.enq.bits.fault)
    io.checkedAddress := BoringUtils.bore(dut.checked.get.enq.bits.request.address)
    io.checkedData := BoringUtils.bore(dut.checked.get.enq.bits.request.data)
    io.checkedSize := BoringUtils.bore(dut.checked.get.enq.bits.request.size)
    io.checkedMask := BoringUtils.bore(dut.checked.get.enq.bits.request.mask)
    io.checkedWrite := BoringUtils.bore(dut.checked.get.enq.bits.request.write)
    io.checkedFrozen := BoringUtils.bore(dut.head.frozenStorePresent.get)
    io.checkedOrigin := BoringUtils.bore(dut.head.canonicalStoreOrigin.get)
    io.checkedVa := BoringUtils.bore(dut.head.originalVirtualAddress.get)
}

object FrozenCheckedFlowGsimMain extends App {
    require(args.length == 3 && args.drop(1).forall(Set("0", "1")), "output enabled queued-head")
    ChiselStage.emitCHIRRTLFile(new FrozenCheckedFlowGsim(args(1) == "1", args(2) == "1"),
        Array("--target-dir", args.head))
}
