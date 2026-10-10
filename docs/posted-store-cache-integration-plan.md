# Posted cache integration: shared interface freeze 1

Delivery note (2026-10-10): this document preserves the initial checkpoint and
its follow-ups. Current frozen-component results, combined-source limits and
remaining checks are in [the integration review](posted-store-delivery-review.md).

Base: component-qualified local 38b5c10c61261f1aa2031b95037bd5cb54b6e226,
source tree ccab58e99eccd48ef0ef0644fd9a1330691ae5e1. This new worktree is
posted-store-cache-integration-r1, branch rebuild/posted-store-cache-r1.
The published component source remains frozen. This interface-only addition
has not been compiled or simulated; its next gate includes the cache wiring.

## Exact optional boundary

PostedStoreCachePort(c) is defined in PostedStoreCachePort.scala. The cache
exposes io.posted: Option[PostedStoreCachePort]. Its cache-view fields are:

- requestProof: Input(Valid(new PostedStoreProof(c))). valid means the unchanged
  upstream request carries a captured CPU proof. It is not a second ready/valid
  transaction. Only upstream.request.fire transports either payload.
- contextEpoch: Input(UInt(c.epochBits.W)). The same CPU-owned epoch is captured
  at actual head authorization, preserved by all queues and supplied here.
- seal: Input(Bool()). Seals runs; never cancels accepted work or prevents its
  request/response, C/D/E, token, WB or probe drain.
- endEpisode: Input(Bool()). Integration proves accepted upstream SB/FIFO,
  cache-owner, posted WB and required coherence responsibility have all drained,
  and there is no held committed offer or same-edge accepted posted transfer.
  A truly empty episode may close with an authorized context change.
- busy: Output(Bool()). Accepted cache-owner/token/fallback responsibility,
  including the initial policy of retaining owners through attached ReleaseAck.
  It excludes raw upstream valid and episodeActive.
- episodeActive: Output(Bool()). Retained cohort identity; it is not a busy
  cause. Local line-count zero never closes it automatically.

Producer and cache proof widths must match: tokenTagBits = p.tagBits,
tokenIndexBits = p.robBits, epochBits = 32, generationBits = 64 for production.
CPU transport can construct a shape-only PostedStoreMergeConfig(enabled=false)
with those token widths; owner config validation belongs to real cache assembly.
The valid sidecar and all proof fields stay stable with the held DataRequest,
including before any owner admission. DataRequest and DataResponseBuffer stay
unchanged. Request-only response buffers are wired around in their enclosing
assembly, since they introduce no request storage.

Constructor additions, all at the end with defaults:

- CoherentLineCachePort(params, postedConfig: Option[PostedStoreMergeConfig] = None)
- CoherentLineCacheModule(params, postedConfig: Option[PostedStoreMergeConfig] = None)
- CoherentLineCacheModule.build(..., postedConfig: Option[PostedStoreMergeConfig] = None)
- NonBlockingCoherentLineCache(..., postedConfig: Option[PostedStoreMergeConfig] = None)

None elaborates no extra port or state. Some requires c.enabled, original
readMshrs = 2, exact equality of cacheSets/ways/readMshrs/responseEntries/
writebackEntries to the instantiated hardware, and c.requireCacheAperture(base,
bytes). The successful-RAM interval comes from the actual legacy physical
StoreBuffer contract and must lie wholly inside this private cache aperture.
There is no cache feature Boolean inside CoherentCacheConcurrency: optional
config is sufficient, avoiding two inconsistent switches. The CPU author owns
its OooParams default-OFF switch and every profile/assembly prerequisite.

## Exclusive production editing ownership

Cache author: PostedStoreCachePort.scala, CoherentCacheConcurrency.scala,
NonBlockingCoherentLineCache.scala, TileLinkLineAcquireEngine.scala; new cache
fixture/oracle/docs only. Existing PostedStoreMerge/Proof behavior stays fixed
unless an independently reviewed integration finding requires a new gate.

CPU proof author: OooParams.scala, IntegerBackend.scala, LoadStoreUnit.scala,
ParallelLoadStoreUnit.scala, StoreBuffer.scala, IntegerCore.scala,
MachineCore.scala, DataTranslationAdapter.scala, MappedMachineCore.scala,
MachinePlatform.scala, BoardSocTop.scala, FpgaNextConfig.scala and its new CPU
lineage fixture/docs. All platform/profile files belong to that author.
DataRequest and DataResponseBuffer are not edited by either author.

The CPU author captures authority only from actual committed head transfers
and the existing physical successful-RAM/PMP contract, including ordinary
StoreBuffer early ACK with fastBufferedStoreRetire at its current value.
The sidecar is captured under each existing payload handshake in LSU/FIFO/SB/
translation ingress, saved miss, translated and checked storage. The checked
boundary can preserve and final-check original authority; identity translation
cannot manufacture it. The common ordered gate is before APLIC routing.
Already accepted loads must retain drain progress; a blocked nonposted request
and younger queued stores cannot be counted in its own older-drain predicate.
Local forwarding and new launch gates need explicit policies and assertions.

## Exact cache lifecycle plan

1. Instantiate the qualified owner only for Some. New-line admission requires
   actual absent/N target, original free MSHR/set, original responseTail credit
   and conservative legacy maintenance readiness. Resident hits and upgrades
   remain legacy. Joins take only the owner's unchanged physical reservation
   and one original response credit. The first episode waits for already
   accepted legacy miss/PF/WB/bypass/probe/response activity to drain.
2. Treat owner.enq as an atomic cache admission bridge for normal merges:
   present a pulse only when original resources and owner.ready can commit on
   the same upstream.request.fire. Upstream request/proof held assertions cover
   the full wait independently. This avoids locking a join choice that becomes
   sealed/resident while waiting for response credits. No resource is reserved
   merely to satisfy stability. Exhausted fallback retains its held path and
   receives legacy ready only with responseSpace.
3. At new acceptance, save posted kind/context/reservation in the original
   MSHR, pending request/index/victim tag as before. Each accepted member saves
   its full member in the original response ticket and completes that response
   with success. Actual upstream.response.fire generates exactly one owner ACK.
   Posted refill/install/release never reads or writes the old response ticket.
4. Posted new admission defers direct eviction until the next real queued
   startEviction, so the owner is live before exact victim ticket attachment.
   Save posted WB lineage at startEviction in the original physical slot;
   attach/sent/complete use this saved context/reservation/ticket until real
   ReleaseAck. Sent comes only from actual C-last. Preserve existing C-last to
   Acquire overlap. The conservative owner waits for its attached ReleaseAck;
   this is not the later WB-reservation optimization. For WB1, do not reuse a
   completing posted ticket on that same edge. OFF scheduling stays exact.
5. Keep the original acquire engine entries/source IDs. Only ON expands tag
   metadata with explicit normal/PF/posted kind and full owner generation/slot
   plus original MSHR. Add an optional engine issued event carrying the saved
   tag on actual A.fire, not engine.request.fire. Engine response is after real
   E; validate its kind/full owner/MSHR and T/full-data before owner.refill.
6. Posted engine completion captures into the existing owner's per-line data,
   allowing reversed response order. Ordinary completion retains the original
   path. Oldest owner.install.fire selects the one actual tag/data write site,
   sets tag/valid/dirty once and marks that MSHR installed. Select the combined
   normal/posted/hit payload and enables ahead of each existing Mem.write call.
   No extra tag/data write port is introduced.
7. Pre-A posted absent targets may answer real probes N. From actual A through
   E/refill/install they block; after installation probes may invalidate while
   ACK/token/resource drain is held. Those later events never write SRAM.
   Exact pre-capture victim removal produces victimCancelled once. Gate new
   PF candidates and acquisitions during an episode or held committed intent,
   while existing traffic drains. Token drains are accepted in order; owner
   released.fire alone frees its retained original MSHR/set after all members
   and its exact WB finish.
8. Keep OFF counts/ports and default path identical. Validate original MSHR
   1/2/4 and WB 1/2/4 legal cases, strict ON geometry, no new SRAM write sites,
   actual response-credit reuse, and physical source-count census.

## Next coherent gates

A real cache/engine wrapper first uses explicit component authority premises,
real SRAM, actual A/C/D/E transport and independently authored raw byte intent.
It distinguishes a synthetic transport schedule from a reachable real home
schedule. Cover two lines and reordered refill, ticket reuse, pre-A mutation,
real probes before A/after E/after install/held ACK, clean/dirty victims,
ReleaseAck retention, errors/no resurrection, bytes and flush. A separate real
home wrapper establishes reachable coherence cases; a separate CPU wrapper
establishes actual ROB-head lineage, precise virtual faults and ordering. No
component premise substitutes for either proof. Only after those pass is a
fresh same-guest A/B and resource census meaningful.

The actual cache gate must include a held committed request whose response
credit is blocked while an older line refills/installs, then accepts that same
unchanged request on the legacy resident-hit path. Its ready cone must contain
no feedback through cpuFire, owner.accepted or engine.request.fire. Exhausted
fallback readiness also uses only pre-edge resources. Physical response/MSHR/
WB slots cannot be freed and reassigned on one edge. A victim invalidated
before capture cancels exactly once; a still-valid victim with changed dirty
state retains its original reservation identity but sends the actual required
Release/ReleaseData from the real capture state.

## Exhaustion fallback tail correction

The integrated initial owner fallback ACK is insufficient to close the cache
episode when a legacy dirty miss overlaps refill with ReleaseAck. The cache
therefore retains a conservative fallbackDrainActive and captured epoch from
actual fallback.fire through full accepted resource drain. The busy/context/
endEpisode boundary includes it. The drain predicate excludes new held proof
and nonposted requests, raw probe/flush offers and episodeActive; an actual
probe accepted on the proposed clear edge extends responsibility. Original
MSHR/WB/response state and real A/C/D/E events establish the drain. This is
explicit full-episode retention, not per-owner WB reservation/reclamation.
The old gen2 model is rejected by the independent manager's unacknowledged
Release ledger; no RTL-derived WB mask supplies expected responsibility.
