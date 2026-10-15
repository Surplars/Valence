package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.TLParams
import soc.core.ooo._

/** Constructor-only scope checks. No runtime or physical qualification is implied. */
object SharedLru76FactoryConfigMain extends App {
    val reviewed = SharedLru76Profile.on.cache.copy(futureHomeWayReservation = false, storePrefetchLruVictim = false)
    require(reviewed == AreaFourthResourceProfile.on.cache && reviewed == TimingReady73Profile.on.cache)
    require(SharedFuture75Profile.on.cache == reviewed.copy(futureHomeWayReservation = true))
    val boardBase = BoardSocConfig.ramBase
    val boardBytes = BigInt(2) * 1024 * 1024 * 1024
    val posted = PostedStoreMergeConfig(enabled = true, guaranteedBase = boardBase, guaranteedBytes = boardBytes)
    var checked = 0
    def check(label: String, expected: Boolean, concurrency: CoherentCacheConcurrency = reviewed,
        allow: Boolean = false, base: BigInt = boardBase, bytes: BigInt = boardBytes,
        lines: Int = 512, params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 1),
        tags: CacheTagConfig = CacheTagConfig(compact = true, bankedStorage = true),
        post: Option[PostedStoreMergeConfig] = Some(posted),
        returns: Option[CpuReturnConfig] = Some(CpuReturnConfig(4, 2, true)),
        probe: Boolean = true, local: Boolean = true): Unit = {
        ChiselStage.elaborate(new Module {
            val cache = CoherentLineCacheModule.build(base, bytes, lines, params, 2, concurrency, tags,
                post, returns, probe, local, allow).asInstanceOf[NonBlockingCoherentLineCache]
            require(cache.shareStoreWriteData == expected, "shared-write guard: " + label)
        })
        checked += 1
    }
    check("historical exact73/74", true)
    check("historical future75", false, reviewed.copy(futureHomeWayReservation = true))
    check("unqualified LRU only", false, reviewed.copy(storePrefetchLruVictim = true))
    check("future LRU default OFF", false, SharedLru76Profile.on.cache)
    check("new76 explicit qualified", true, SharedLru76Profile.on.cache, allow = true)
    check("allow without future", false, reviewed.copy(storePrefetchLruVictim = true), allow = true)
    check("allow without LRU", false, reviewed.copy(futureHomeWayReservation = true), allow = true)
    val candidate = SharedLru76Profile.on.cache
    check("unreviewed concurrency bit", false, candidate.copy(prefetchBreakOnStore = true), allow = true)
    check("unreviewed distinct release", false, candidate.copy(distinctWayRelease = true), allow = true)
    check("other base", false, candidate, allow = true, base = boardBase + 64,
        post = Some(posted.copy(guaranteedBase = boardBase + 64)))
    check("other aperture", false, candidate, allow = true, bytes = boardBytes / 2,
        post = Some(posted.copy(guaranteedBytes = boardBytes / 2)))
    check("other geometry", false, candidate, allow = true, lines = 256,
        post = Some(posted.copy(cacheSets = 128)))
    check("full tags", false, candidate, allow = true, tags = CacheTagConfig(compact = false, bankedStorage = true))
    check("unbanked tags", false, candidate, allow = true, tags = CacheTagConfig(compact = true))
    check("source width", false, candidate, allow = true, params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4, sinkBits = 1))
    check("sink width", false, candidate, allow = true, params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 2))
    check("probe default", false, candidate, allow = true, probe = false)
    check("read default", false, candidate, allow = true, local = false)
    check("return absent", false, candidate, allow = true, returns = None)
    check("posted absent", false, candidate.copy(postedPrefetchCoexistence = false), allow = true, post = None)
    check("posted tag width", false, candidate, allow = true, post = Some(posted.copy(tokenTagBits = 32)))
    check("posted generation width", false, candidate, allow = true, post = Some(posted.copy(generationBits = 32)))
    check("posted epoch width", false, candidate, allow = true, post = Some(posted.copy(epochBits = 16)))
    check("posted inner aperture", false, candidate, allow = true,
        post = Some(posted.copy(guaranteedBytes = boardBytes / 2)))
    ChiselStage.elaborate(new Module {
        val cache = Module(new NonBlockingCoherentLineCache())
        require(!cache.shareStoreWriteData && !cache.registerProbeLookup && !cache.localReadSelection)
    })
    println(s"PASS_SHARED_LRU76_FACTORY actual_constructors=$checked")
}
