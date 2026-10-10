package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._
import soc.bus.tilelink._
import java.nio.file.{Files, Paths}

/** Complete constructor products, including every OooParams flag, not a label. */
object PostedBoardConfiguration {
    private def quote(value: String): String = "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
    private def json(value: Any): String = value match {
        case null => "null"
        case text: String => quote(text)
        case bool: Boolean => bool.toString
        case number: BigInt => number.toString
        case number: Int => number.toString
        case number: Long => number.toString
        case option: Option[_] => option.map(json).getOrElse("null")
        case fields: collection.Map[_, _] => fields.toSeq.sortBy(_._1.toString)
            .map { case (name, item) => quote(name.toString) + ":" + json(item) }.mkString("{", ",", "}")
        case items: Seq[_] => items.map(json).mkString("[", ",", "]")
        case product: Product => json(product.productElementNames.zip(product.productIterator).toMap)
        case other => throw new IllegalArgumentException("unserialized profile value: " + other.getClass.getName)
    }
    def write(c: FpgaNextConfig, directory: String): Unit = {
        val derived = Map[String, Any]("isaProfile" -> c.isaProfile, "issueWidth" -> c.issueWidth,
            "instructionCacheLines" -> c.instructionCacheLines, "dataCacheLines" -> c.dataCacheLines,
            "cacheWays" -> c.cacheWays, "cacheLineBytes" -> c.cacheLineBytes,
            "instructionTranslationEntries" -> 8, "dataTranslationEntries" -> c.dataTranslationEntries,
            "pteCacheEntries" -> 4, "cpuHz" -> c.cpuHz, "uartBaud" -> c.uartBaud,
            "romBase" -> BoardSocConfig.romBase, "romBytes" -> BoardSocConfig.romBytes,
            "ramBase" -> c.ramBase, "ddrBytes" -> c.ddrBytes, "timingProfile" -> c.timingProfile,
            "identityDataFlow" -> c.identityDataFlow, "loadIssueForwarding" -> c.loadIssueForwarding,
            "instructionPrefetch" -> c.instructionPrefetch, "coherentSourceBits" -> 3,
            "coherentSinkBits" -> c.cache.sinkBits, "axiAddressBits" -> 32)
        val document = Map[String, Any]("schema" -> "posted-board-full-profile-v2", "profile" -> c,
            "core" -> c.coreParams, "cache" -> c.cache, "ddr" -> c.ddr, "storage" -> c.storage,
            "tags" -> c.tags, "floatingPointResources" -> c.floatingPointResources,
            "network" -> c.network, "derived" -> derived)
        Files.createDirectories(Paths.get(directory))
        Files.writeString(Paths.get(directory, "profile.json"), json(document) + "\n")
    }
}

class PostedBoardAllocation(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    val pc = UInt(64.W)
    val instruction = UInt(32.W)
}
class PostedBoardChannel[T <: Data](gen: T) extends Bundle {
    val valid = Bool()
    val ready = Bool()
    val bits = gen
}
/** Wide data is exposed as individual scalar words for the pinned GSIM ABI. */
class PostedBoardWords extends Bundle {
    val word0 = UInt(64.W); val word1 = UInt(64.W)
    val word2 = UInt(64.W); val word3 = UInt(64.W)
    val word4 = UInt(64.W); val word5 = UInt(64.W)
    val word6 = UInt(64.W); val word7 = UInt(64.W)
    def words: Seq[UInt] = Seq(word0, word1, word2, word3, word4, word5, word6, word7)
}
class PostedBoardOwner(c: PostedStoreMergeConfig) extends Bundle {
    val accepted = Valid(new PostedStoreAcceptance(c))
    val acknowledged = Valid(new PostedStoreMember(c))
    val acquired = Valid(new PostedLineEvent(c))
    val refillValid = Bool()
    val refillEvent = new PostedLineEvent(c)
    val refillError = Bool()
    val refill = new PostedBoardWords
    val installedValid = Bool()
    val installedEvent = new PostedLineEvent(c)
    val installed = new PostedBoardWords
    val drained = Valid(new PostedStoreMember(c))
    val released = Valid(new PostedLineEvent(c))
    val attached = Valid(new PostedWritebackEvent(c))
    val sent = Valid(new PostedWritebackEvent(c))
    val completed = Valid(new PostedWritebackEvent(c))
    val cancelled = Valid(new PostedLineEvent(c))
    val fallback = Valid(new PostedFallbackAcknowledgement(c))
    val fallbackAck = Valid(new PostedFallbackAcknowledgement(c))
    val failed = Bool()
    val mshrMask = UInt(c.readMshrs.W)
    val postedMask = UInt(c.readMshrs.W)
    val responseMask = UInt(c.responseEntries.W)
    val responseCompleteMask = UInt(c.responseEntries.W)
    val wbMask = UInt(c.writebackEntries.W)
}
class PostedBoardTrace(p: OooParams) extends Bundle {
    private val c = PostedStoreMergeConfig(tokenTagBits = p.tagBits, tokenIndexBits = p.robBits)
    private val tl = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 1)
    val alloc0 = Valid(new PostedBoardAllocation(p))
    val alloc1 = Valid(new PostedBoardAllocation(p))
    val commit0 = Valid(new CommitRecord(p))
    val commit1 = Valid(new CommitRecord(p))
    val headValid = Bool()
    val headToken = new RobToken(p)
    val headPc = UInt(64.W)
    val headInstruction = UInt(32.W)
    val startValid = Bool()
    val startReady = Bool()
    val start = new MemoryOperation(p)
    val completionValid = Bool()
    val completionReady = Bool()
    val completion = new BackendCompletion(p)
    val requestOwner = Valid(new RobToken(p))
    val pmpDenied = Bool()
    val dataPrivilege = UInt(2.W)
    val cache = new PostedCpuBoundary(c)
    val epoch = UInt(32.W)
    val cacheBusy = Bool()
    val cpuBusy = Bool()
    val episodeActive = Bool()
    val seal = Bool()
    val endEpisode = Bool()
    val flushRequest = Bool()
    val cacheFlushDone = Bool()
    val flushReady = Bool()
    val prefetchBusy = Bool()
    val owner = new PostedBoardOwner(c)
    val lineWriteValid = Bool()
    val lineWritePosted = Bool()
    val lineWriteAddress = UInt(64.W)
    val lineWrite = new PostedBoardWords
    val tlA = new PostedBoardChannel(new TLBundleA(tl))
    val tlB = new PostedBoardChannel(new TLBundleB(tl))
    val tlC = new PostedBoardChannel(new TLBundleC(tl))
    val tlD = new PostedBoardChannel(new TLBundleD(tl))
    val tlE = new PostedBoardChannel(new TLBundleE(tl))
}
object PostedBoardProbes {
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
object PostedStoreBoardLineageGsimMain extends App {
    require(args.length == 2 && Set("on", "off").contains(args(1)), "target directory and explicit on/off required")
    val profile = FpgaNextConfig.Selected.copy(dataTranslationEntries = 16,
        virtualRamLoadPrecheck = true, preparedStoreLookahead = true,
        storeNextLinePrefetch = true, storePrefetchMruInsertion = true,
        dmaLineTransfers = true, dmaLineEntries = 4,
        lsuEntries = 4, physicalLoadIngressFlow = true, loadOrderOlderRetire = true,
        fetchPreviousPacket = true, postedStoreMerge = args(1) == "on")
    // Exact options from the independently archived afe85 native OFF/ON export.
    // Constructor equality covers every default as well as selected overrides.
    val referenceOptions = Set("--selected", "--data-translation-entries=16", "--dma-line-transfers",
        "--dma-line-entries=4", "--virtual-ram-load-precheck", "--lsu-entries=4",
        "--physical-load-ingress-flow", "--load-order-older-retire", "--fetch-previous-packet",
        "--prepared-store-lookahead", "--store-next-line-prefetch", "--store-prefetch-mru-insertion") ++
        (if (args(1) == "on") Set("--posted-store-merge") else Set.empty[String])
    val nativeReference = FpgaNextConfig.fromOptions(referenceOptions, defaultSelected = false)
    require(profile == nativeReference && profile.coreParams == nativeReference.coreParams,
        "Board model profile differs from the exact archived native export options")
    require(!profile.precheckedDataRequestFlow && !profile.translatedResponseEmptyFlow &&
        !profile.coreParams.fastBufferedStoreRetire && profile.dmaLineTransfers && profile.dmaLineEntries == 4)
    PostedBoardConfiguration.write(profile, args(0))
    ChiselStage.emitCHIRRTLFile(FpgaNextBoardGsim.build(profile, lineageProbes = true),
        Array("--target-dir", args(0)))
}
