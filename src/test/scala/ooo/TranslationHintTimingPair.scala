package soc.core.ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils

/** Test-only exact-cycle reference. External hosts retain independent owner/permission truth.
  * Mirror inputs, never reference decisions, and compare payload only with its actual validity.
  */
object TranslationHintTimingPair {
    def attach(candidate: DataTranslationAdapter, p: OooParams, translationHitFlow: Boolean): Unit = {
        val reference = Module(new DataTranslationAdapter(p, registerCheckedRequests = true,
            translationHitFlow = translationHitFlow))
        val a = candidate.io
        val b = reference.io
        b.virtual.request.valid := a.virtual.request.valid
        b.virtual.request.bits := a.virtual.request.bits
        b.virtual.response.ready := a.virtual.response.ready
        b.physical.request.ready := a.physical.request.ready
        b.physical.response.valid := a.physical.response.valid
        b.physical.response.bits := a.physical.response.bits
        b.translation.request.ready := a.translation.request.ready
        b.translation.response.valid := a.translation.response.valid
        b.translation.response.bits := a.translation.response.bits
        b.vmState := a.vmState
        b.pmpState := a.pmpState
        b.precheckFlush.foreach(_ := a.precheckFlush.get)
        b.loadPrecheck.foreach(_.request := a.loadPrecheck.get.request)
        b.translationPeek.foreach(_.response := a.translationPeek.get.response)
        b.canonicalStoreOrigin.foreach(_ := a.canonicalStoreOrigin.get)
        b.frozenStoreProof.foreach(_ := a.frozenStoreProof.get)
        b.posted.foreach { posted =>
            posted.upstreamProof := a.posted.get.upstreamProof
            posted.aggregateDrained := a.posted.get.aggregateDrained
            posted.externalBusy := a.posted.get.externalBusy
        }

        def sameValid(left: ValidIO[_ <: Data], right: ValidIO[_ <: Data], name: String): Unit = {
            assert(left.valid === right.valid, name + " valid parity")
            when(left.valid) { assert(left.bits.asUInt === right.bits.asUInt, name + " valid payload parity") }
        }
        def samePort(left: ReadyValidIO[_ <: Data], right: ReadyValidIO[_ <: Data], name: String): Unit = {
            assert(left.valid === right.valid && left.ready === right.ready, name + " valid/ready parity")
            when(left.valid) { assert(left.bits.asUInt === right.bits.asUInt, name + " valid payload parity") }
        }
        samePort(a.virtual.request, b.virtual.request, "ingress")
        samePort(a.virtual.response, b.virtual.response, "ordered response")
        samePort(a.physical.request, b.physical.request, "physical request and captured hint")
        samePort(a.physical.response, b.physical.response, "physical response")
        samePort(a.translation.request, b.translation.request, "demand translation")
        samePort(a.translation.response, b.translation.response, "translation reply")
        a.canonicalStoreCertificate.foreach(c => sameValid(c, b.canonicalStoreCertificate.get, "certificate"))
        a.loadPrecheck.foreach { precheck =>
            sameValid(precheck.response, b.loadPrecheck.get.response, "precheck response")
            assert(precheck.epoch === b.loadPrecheck.get.epoch &&
                precheck.stable === b.loadPrecheck.get.stable, "authorization context parity")
        }
        a.translationPeek.foreach(peek => sameValid(peek.request, b.translationPeek.get.request, "peek request"))
        a.posted.foreach { posted =>
            sameValid(posted.requestProof, b.posted.get.requestProof, "posted proof")
            assert(posted.contextEpoch === b.posted.get.contextEpoch &&
                posted.contextChanging === b.posted.get.contextChanging, "posted context parity")
        }
        assert(a.idle === b.idle && a.pageFault === b.pageFault && a.physicalRequest === b.physicalRequest,
            "adapter status/event parity")
        // Compare actual checked acceptance, not unqualified raw head bits while empty.
        val checkedValid = BoringUtils.bore(candidate.checked.get.enq.valid)
        assert(checkedValid === BoringUtils.bore(reference.checked.get.enq.valid), "checked valid parity")
        assert(BoringUtils.bore(candidate.checked.get.enq.ready) ===
            BoringUtils.bore(reference.checked.get.enq.ready), "checked ready parity")
        when(checkedValid) {
            val c = BoringUtils.bore(candidate.checked.get.enq.bits)
            val r = BoringUtils.bore(reference.checked.get.enq.bits)
            if (candidate.registerNextLineDecision) {
                val normalized = Wire(new CheckedDataRequest(p))
                normalized.request := c.request
                normalized.request.prefetchNextAllowed := c.request.prefetchNextAllowed &&
                    !PmpDecisionSummary.denied(c.nextLineDecision.get)
                normalized.fault := c.fault; normalized.pageFault := c.pageFault
                normalized.postedProof.foreach(_ := c.postedProof.get)
                assert(normalized.asUInt === r.asUInt, "classified checked offered authority parity")
            } else assert(c.asUInt === r.asUInt, "checked offered record parity")
        }
        if (translationHitFlow) assert(BoringUtils.bore(candidate.translationHitOffer) === BoringUtils.bore(reference.translationHitOffer) &&
            BoringUtils.bore(candidate.translationHitPass) === BoringUtils.bore(reference.translationHitPass),
            "same-cycle hit offer/fire parity")
        assert(BoringUtils.bore(candidate.precheckedPass) === BoringUtils.bore(reference.precheckedPass) &&
            BoringUtils.bore(candidate.identityPass) === BoringUtils.bore(reference.identityPass) &&
            BoringUtils.bore(candidate.physicalIngressPass) === BoringUtils.bore(reference.physicalIngressPass),
            "physical/prechecked/identity acceptance parity")
    }
}
