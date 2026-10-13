package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Exact old/new adapter pair. The independent host supplies original owners and delayed translations.
  * The high RAM aperture checks full PA transport beyond 32 bits. No shadow state affects the DUT.
  */
class TranslatedFrozenProofGsim(hintTimingPair: Boolean = false) extends Module {
    val p = PendingStoreProofFixture.params(enabled = false).copy(speculativeRamBase = BigInt("180010000", 16),
        dataNextLinePrefetch = hintTimingPair, dataStoreNextLinePrefetch = hintTimingPair)
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val origin = Input(Valid(new CanonicalStoreOrigin(p)))
        val frozen = Input(Valid(new FrozenStoreProof))
        val physical = new DataPort
        val translation = new SvTranslationPort
        val context = Input(new VmCsrState)
        val pmpCfg = Input(UInt(8.W))
        val flush = Input(Bool())
        val epoch = Output(UInt(32.W))
        val stable = Output(Bool())
        val checked = Output(Valid(new CanonicalStoreCertificate(p)))
        val idle = Output(Bool())
    })
    val compact = Module(new DataTranslationAdapter(p, registerCheckedRequests = true,
        translationHitFlow = hintTimingPair, queuedHeadSelection = hintTimingPair, alignedNextLinePmp = hintTimingPair))
    val original = Module(new ReferenceDataTranslationAdapter(p, registerCheckedRequests = true,
        translationHitFlow = hintTimingPair))
    val pmp = PendingStoreProofFixture.pmp(io.pmpCfg, ((BigInt(1) << 54) - 1).U(54.W))
    for (dut <- Seq(compact.io, original.io)) {
        dut.virtual.request.valid := io.upstream.request.valid
        dut.virtual.request.bits := io.upstream.request.bits
        dut.virtual.response.ready := io.upstream.response.ready
        dut.canonicalStoreOrigin.get := io.origin
        dut.frozenStoreProof.get := io.frozen
        dut.vmState := io.context
        dut.pmpState := pmp
        dut.precheckFlush.get := io.flush
        dut.loadPrecheck.get.request := 0.U.asTypeOf(dut.loadPrecheck.get.request)
        dut.translationPeek.get.response := 0.U.asTypeOf(dut.translationPeek.get.response)
        dut.physical.request.ready := io.physical.request.ready
        dut.physical.response.valid := io.physical.response.valid
        dut.physical.response.bits := io.physical.response.bits
        dut.translation.request.ready := io.translation.request.ready
        dut.translation.response.valid := io.translation.response.valid
        dut.translation.response.bits := io.translation.response.bits
    }
    io.upstream.request.ready := compact.io.virtual.request.ready
    io.upstream.response.valid := compact.io.virtual.response.valid
    io.upstream.response.bits := compact.io.virtual.response.bits
    io.physical.request.valid := compact.io.physical.request.valid
    io.physical.request.bits := compact.io.physical.request.bits
    io.physical.response.ready := compact.io.physical.response.ready
    io.translation.request.valid := compact.io.translation.request.valid
    io.translation.request.bits := compact.io.translation.request.bits
    io.translation.response.ready := compact.io.translation.response.ready
    io.epoch := compact.io.loadPrecheck.get.epoch
    io.stable := compact.io.loadPrecheck.get.stable
    io.checked := compact.io.canonicalStoreCertificate.get
    io.idle := compact.io.idle

    def sameOffer(left: ReadyValidIO[_ <: Data], right: ReadyValidIO[_ <: Data], label: String): Unit = {
        assert(left.valid === right.valid, label + " valid parity")
        when(left.valid) { assert(left.bits.asUInt === right.bits.asUInt, label + " payload parity") }
    }
    sameOffer(compact.io.physical.request, original.io.physical.request, "physical request")
    sameOffer(compact.io.virtual.response, original.io.virtual.response, "ordered response")
    sameOffer(compact.io.translation.request, original.io.translation.request, "demand translation")
    assert(compact.io.canonicalStoreCertificate.get.valid === original.io.canonicalStoreCertificate.get.valid,
        "checked certificate valid parity")
    when(compact.io.canonicalStoreCertificate.get.valid) {
        assert(compact.io.canonicalStoreCertificate.get.bits.asUInt === original.io.canonicalStoreCertificate.get.bits.asUInt,
            "checked certificate payload parity")
    }
    assert(compact.io.virtual.request.ready === original.io.virtual.request.ready, "upstream ready parity")
    assert(compact.io.physical.response.ready === original.io.physical.response.ready, "physical response ready parity")
    assert(compact.io.translation.response.ready === original.io.translation.response.ready, "translation reply ready parity")
    assert(compact.io.loadPrecheck.get.epoch === original.io.loadPrecheck.get.epoch &&
        compact.io.loadPrecheck.get.stable === original.io.loadPrecheck.get.stable &&
        compact.io.idle === original.io.idle, "context and idle parity")
}

object TranslatedFrozenProofGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TranslatedFrozenProofGsim, Array("--target-dir", args.head))
}
