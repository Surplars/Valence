package soc.core.ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.bus.tilelink.TLParams

/** Same public inputs, old production cache reference; host owns byte/protocol truth. */
object CacheReadSelectionPair {
    def attach(candidate: NonBlockingCoherentLineCache, base: BigInt, bytes: BigInt, lines: Int,
        params: TLParams, ways: Int, concurrency: CoherentCacheConcurrency, tagConfig: CacheTagConfig,
        postedConfig: Option[PostedStoreMergeConfig], registerProbeLookup: Boolean): Unit = {
        require(candidate.localReadSelection)
        val reference = Module(new NonBlockingCoherentLineCache(base, bytes, lines, params, ways,
            concurrency, tagConfig, postedConfig, registerProbeLookup = registerProbeLookup))
        val a = candidate.io
        val b = reference.io
        b.upstream.request.valid := a.upstream.request.valid
        b.upstream.request.bits := a.upstream.request.bits
        b.upstream.response.ready := a.upstream.response.ready
        b.downstream.request.ready := a.downstream.request.ready
        b.downstream.response.valid := a.downstream.response.valid
        b.downstream.response.bits := a.downstream.response.bits
        b.tl.a.ready := a.tl.a.ready
        b.tl.b.valid := a.tl.b.valid
        b.tl.b.bits := a.tl.b.bits
        b.tl.c.ready := a.tl.c.ready
        b.tl.d.valid := a.tl.d.valid
        b.tl.d.bits := a.tl.d.bits
        b.tl.e.ready := a.tl.e.ready
        b.flushRequest := a.flushRequest
        b.posted.foreach { x =>
            x.requestProof := a.posted.get.requestProof
            x.contextEpoch := a.posted.get.contextEpoch
            x.seal := a.posted.get.seal
            x.endEpisode := a.posted.get.endEpisode
        }
        require(!concurrency.internalLineGrant, "focused pair uses standard real TL beat interface")
        def port(x: ReadyValidIO[_ <: Data], y: ReadyValidIO[_ <: Data], label: String): Unit = {
            assert(x.valid === y.valid && x.ready === y.ready, "cache pair " + label + " handshake")
            when(x.valid) { assert(x.bits.asUInt === y.bits.asUInt, "cache pair " + label + " payload") }
        }
        def event(x: ValidIO[_ <: Data], y: ValidIO[_ <: Data], label: String): Unit = {
            assert(x.valid === y.valid, "cache pair " + label + " valid")
            when(x.valid) { assert(x.bits.asUInt === y.bits.asUInt, "cache pair " + label + " payload") }
        }
        port(a.upstream.request, b.upstream.request, "CPU request")
        port(a.upstream.response, b.upstream.response, "CPU response")
        port(a.downstream.request, b.downstream.request, "bypass request")
        port(a.downstream.response, b.downstream.response, "bypass response")
        port(a.tl.a, b.tl.a, "A"); port(a.tl.b, b.tl.b, "B")
        port(a.tl.c, b.tl.c, "C"); port(a.tl.d, b.tl.d, "D"); port(a.tl.e, b.tl.e, "E")
        assert(a.flushDone === b.flushDone && a.prefetchBusy === b.prefetchBusy &&
            a.hit === b.hit && a.miss === b.miss && a.prefetch.asUInt === b.prefetch.asUInt &&
            a.profile.asUInt === b.profile.asUInt, "cache pair status/profile")
        a.posted.foreach { x =>
            assert(x.busy === b.posted.get.busy && x.episodeActive === b.posted.get.episodeActive,
                "cache pair posted lifetime")
            val xobs = BoringUtils.bore(candidate.observationPosted.get)
            val yobs = BoringUtils.bore(reference.observationPosted.get)
            event(xobs.accepted, yobs.accepted, "accepted")
            event(xobs.acknowledged, yobs.acknowledged, "acknowledged")
            event(xobs.acquired, yobs.acquired, "acquired")
            event(xobs.installed, yobs.installed, "installed")
            event(xobs.drained, yobs.drained, "drained")
            event(xobs.released, yobs.released, "released")
            event(xobs.attached, yobs.attached, "attached")
            event(xobs.sent, yobs.sent, "sent")
            event(xobs.completed, yobs.completed, "completed")
            event(xobs.cancelled, yobs.cancelled, "cancelled")
            event(xobs.fallback, yobs.fallback, "fallback")
            event(xobs.fallbackAck, yobs.fallbackAck, "fallbackAck")
            assert(xobs.refillValid === yobs.refillValid, "cache pair refill valid")
            when(xobs.refillValid) {
                assert(xobs.refillEvent.asUInt === yobs.refillEvent.asUInt &&
                    xobs.refillData === yobs.refillData && xobs.refillError === yobs.refillError,
                    "cache pair refill owner/bytes")
            }
            assert(xobs.failed === yobs.failed && xobs.mshrMask === yobs.mshrMask &&
                xobs.postedMask === yobs.postedMask && xobs.responseMask === yobs.responseMask &&
                xobs.responseCompleteMask === yobs.responseCompleteMask && xobs.wbMask === yobs.wbMask,
                "cache pair responsibility masks")
        }
        val xwrite = BoringUtils.bore(candidate.observationLineWrite)
        val ywrite = BoringUtils.bore(reference.observationLineWrite)
        assert(xwrite.valid === ywrite.valid, "cache pair line write valid")
        when(xwrite.valid) { assert(xwrite.asUInt === ywrite.asUInt, "cache pair exact line write") }
    }
}
