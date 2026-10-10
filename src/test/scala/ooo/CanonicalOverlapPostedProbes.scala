package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._
import soc.bus.tilelink._
import java.nio.file.{Files, Paths}

object CanonicalOverlapPostedProbes {
    def connect(out: PostedBoardTrace, board: BoardSocTop, profile: FpgaNextConfig): Unit = {
        val p = profile.coreParams
        require(p.memoryEntries == 4 && p.tagBits == 64 && Set(4, 5, 6).contains(p.robBits) &&
            profile.dataCacheLines == 512 && profile.cacheWays == 2 &&
            profile.cache.readMshrs == 2 && profile.cache.responseEntries == 2 &&
            profile.cache.writebackEntries == 2 && profile.cache.sinkBits == 1)
        val cache = board.platform.privateCache.get match {
            case value: NonBlockingCoherentLineCache => value
            case _ => throw new IllegalArgumentException("composition fixture requires real nonblocking private cache")
        }
        val mapped = board.platform.core
        val backend = mapped.core.core.backend
        def tap[T <: Data](value: T): T = BoringUtils.bore(value)
        for ((allocation, lane) <- Seq((out.alloc0, 0), (out.alloc1, 1))) {
            allocation.valid := tap(backend.io.renamed(lane).valid)
            allocation.bits.token := tap(backend.io.renamed(lane).bits.token)
            allocation.bits.pc := tap(backend.io.allocate(lane).bits.rename.pc)
            allocation.bits.instruction := tap(backend.io.allocate(lane).bits.rename.instruction)
        }
        out.commit0 := tap(mapped.io.commit(0)); out.commit1 := tap(mapped.io.commit(1))
        out.headValid := tap(backend.ledger.io.headValid)
        out.headToken := tap(backend.headRenamed.token)
        out.headPc := tap(backend.headRequest.rename.pc)
        out.headInstruction := tap(backend.headRequest.rename.instruction)
        out.startValid := tap(backend.lsu.io.start.valid)
        out.startReady := tap(backend.lsu.io.start.ready)
        out.start := tap(backend.lsu.io.start.bits)
        out.completionValid := tap(backend.lsu.io.complete.valid)
        out.completionReady := tap(backend.lsu.io.complete.ready)
        out.completion := tap(backend.lsu.io.complete.bits)
        out.requestOwner := tap(backend.lsu.io.requestOwner)
        out.pmpDenied := tap(backend.pmpCheck.io.denied)
        out.dataPrivilege := tap(backend.dataPrivilege)
        out.cache.valid := tap(cache.io.upstream.request.valid)
        out.cache.ready := tap(cache.io.upstream.request.ready)
        out.cache.request := tap(cache.io.upstream.request.bits)
        out.cache.proof := cache.io.posted.map(x => tap(x.requestProof)).getOrElse(0.U.asTypeOf(out.cache.proof))
        out.cache.responseValid := tap(cache.io.upstream.response.valid)
        out.cache.responseReady := tap(cache.io.upstream.response.ready)
        out.cache.response := tap(cache.io.upstream.response.bits)
        out.epoch := cache.io.posted.map(x => tap(x.contextEpoch)).getOrElse(0.U)
        out.cacheBusy := cache.io.posted.map(x => tap(x.busy)).getOrElse(false.B)
        out.cpuBusy := tap(mapped.io.memoryBusy)
        out.episodeActive := cache.io.posted.map(x => tap(x.episodeActive)).getOrElse(false.B)
        out.seal := cache.io.posted.map(x => tap(x.seal)).getOrElse(false.B)
        out.endEpisode := cache.io.posted.map(x => tap(x.endEpisode)).getOrElse(false.B)
        out.flushRequest := tap(mapped.io.fenceIFlush)
        out.cacheFlushDone := tap(cache.io.flushDone)
        out.flushReady := tap(mapped.io.fenceIFlushReady)
        out.prefetchBusy := tap(cache.io.prefetchBusy)
        out.owner := 0.U.asTypeOf(out.owner)
        cache.observationPosted.foreach { value =>
            val observed = tap(value)
            for (name <- Seq("accepted", "acknowledged", "acquired", "refillValid", "refillEvent",
                "refillError", "drained", "released", "attached", "sent", "completed", "cancelled",
                "fallback", "fallbackAck", "failed", "mshrMask", "postedMask", "responseMask",
                "responseCompleteMask", "wbMask")) out.owner.elements(name) := observed.elements(name)
            out.owner.installedValid := observed.installed.valid
            out.owner.installedEvent.context := observed.installed.bits.context
            out.owner.installedEvent.reservation := observed.installed.bits.reservation
            out.owner.refill.words.zipWithIndex.foreach { case (word, index) => word := observed.refillData(64 * index + 63, 64 * index) }
            out.owner.installed.words.zipWithIndex.foreach { case (word, index) => word := observed.installed.bits.data(64 * index + 63, 64 * index) }
        }
        val line = tap(cache.observationLineWrite)
        out.lineWriteValid := line.valid; out.lineWritePosted := line.posted; out.lineWriteAddress := line.address
        out.lineWrite.words.zipWithIndex.foreach { case (word, index) => word := line.data(64 * index + 63, 64 * index) }
        def channel[T <: Data](target: PostedBoardChannel[T], source: DecoupledIO[T]): Unit = {
            target.valid := tap(source.valid); target.ready := tap(source.ready); target.bits := tap(source.bits)
        }
        channel(out.tlA, cache.io.tl.a); channel(out.tlB, cache.io.tl.b)
        channel(out.tlC, cache.io.tl.c); channel(out.tlD, cache.io.tl.d); channel(out.tlE, cache.io.tl.e)
    }
}
