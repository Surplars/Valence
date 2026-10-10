# New posted-store owner checkpoint

Status: PASS_STANDALONE_OWNER_ONLY at source d0408c050477f1628d94fcbe51dbaac133e80bd7
(tree bc55b9ec478fad5852494f2c6533ae87dd35a55c). Three Scala/config/elaboration
checks, 19 generation64 GSIM cases and one distinct generation2 exhaustion
case passed with ASan/UBSan. The component uses explicit environmental
premises. Production CPU/cache/home integration, performance and synthesis
remain unqualified. No profile enables it. Existing production sources,
DataRequest, virtual-store behavior and fastBufferedStoreRetire are unchanged.
`component-results.json` records the exact tested source and full receipt hash.

Run the small host check with:

    python3 simulator/gsim/posted_merge_rebuild/run_host_checks.py

The suite currently has 22 host test cases and 10 detected semantic mutants.
`host-results.json` binds the oracle/test hashes and preserves all test output.
These checks establish oracle sensitivity and intended event contracts, not
RTL behavior, real-home reachability, CPU head authority or speedup.

## Frozen interface, checkpoint 1

PostedStoreOffer carries only immutable DataRequest and captured
PostedStoreProof. The proof retains full ROB tag/index, original physical
address/data/mask/size and epoch, with head/PMP/integer/physical/accepted legacy
StoreBuffer/final-checked obligations. DataRequest itself is unchanged. Both
ordinary physical StoreBuffer early-ACK and fast head paths are in the intended
integration scope; no fast path is enabled to manufacture a benefit.

cacheAdmission is a separate acceptance-time input containing real response
credit availability/ticket and optional new-line physical reservation.
Candidate MSHR/way/victim decisions may change while an original offer stalls.
They are not its immutable payload and do not reserve resources merely because
valid is high. On enq.fire, the cache atomically commits the actual resources.
A same-line join retains its owner's reservation and consumes one existing
response credit.

targetAbsent must describe an actual N/absent-line miss. A resident hit or
B-to-T upgrade remains on the legacy path: it may return a data-free Grant,
whereas this owner requires full data, T permission and E. The config's
requireCacheAperture method must be called with the real cache aperture and
rejects any successful-RAM interval not wholly contained in that aperture.
The standalone fixture calls it for its explicit environment; production
assembly integration is still pending.

Shared identities agreed with the independent WB reviewer:

- PostedLineOwner {slot, generation}: full identity; generation never wraps.
- PostedLineContext {owner, cohortRoot, epoch, lineAddress}: root is the full
  first owner of the continuing episode, retained after that owner releases.
- PostedCacheReservation {mshr,set,way,victimValid,victimDirty,victimAddress}.
- PostedWritebackTicket {slot,owner}: at most one lifetime victim reservation
  or release per full owner, including cancellation. No separate counter.

Events and observations:

- accepted: enq.fire and atomic original response/MSHR/set/victim admission.
- acknowledged: actual ordered cache upstream.response.fire with full member;
  valid alone is not ACK. No posted refill rewrites that response ticket.
- acquireIssued: actual TL A.fire, distinct from engine.request.fire.
- refill: original engine completion after eight real GrantData beats and E.
  Two reserved owner buffers accept out-of-order returns without holding the
  older return behind a blocked younger engine result.
- install.fire: actual once-only SRAM/tag/dirty installation, oldest
  uninstalled owner first. Joins stop before refill capture. A post-install
  probe is never undone by a later token ACK/drain/resource release.
- drained.fire: oldest full token whose real ACK and installation occurred.
- writebackAttached: original startEviction captures exact context,
  reservation and physical WB ticket. This is not a new WB allocator.
- writebackSent: actual original C-last for that exact ticket. Original
  C-last-to-Acquire overlap remains legal before ReleaseAck.
- writebackCompleted: actual successful in-range ReleaseAck from saved full
  lineage, never reconstructed from a current MSHR.
- victimCancelled: exact real pre-capture probe removal. It permanently
  resolves that owner's one victim opportunity, without a fictitious ACK.
- released.fire: real posted MSHR/set release after all tokens drain and any
  attached WB receives ReleaseAck. This is the initial conservative policy,
  not a permanent liveness prerequisite of the shared WB completion type.
- fallback.fire: after finite generation exhaustion and local drain, hands
  the unchanged request/proof to the legacy path. Its captured full token and
  response ticket remain busy until actual fallback ACK.
- endEpisode: integration event after registered aggregate drain. It cannot
  coincide with local responsibility or held ingress. Local line-count zero
  cannot end a cohort while accepted SB/FIFO or coherence work remains.

Eight 8-byte stores in an installed line still create an eight-token drain
tail plus the registered resource-release boundary, and any attached WB ACK
may extend retention. This is a known conservative cost to measure. A later
separately qualified WB optimization may retain full WB lineage independently
and release an MSHR sooner. No historical speedup is claimed.

## Busy domains and integration obligations

busy is only this component's accepted line/token/fallback/failure
responsibility. episodeActive retains identity and is not a busy cause.
The common CPU drain domain must include accepted irrevocable StoreBuffer/FIFO
transfers, local owner busy, independently retained posted WB and required
coherence work. The SB-to-cache handoff must preserve the pre/post-edge union;
neither local early ACK nor returning a response credit may create a gap.

The checked-to-APLIC ordered gate sees only older posted responsibility. Never
include the blocked non-posted request or younger queued stores. Already
accepted loads retain request/response drain permission after a new busy
state. Later wiring must distinguish forwarding from an already accepted
matching SB entry from a new independent access, documenting its conservative
policy instead of using raw upstream valid as busy. This wiring is not built.

No new prefetch is admitted during a posted episode/held ingress. Existing
normal/PF/WB work drains before first admission. Already accepted stores,
C/D/E and probes continue when a fence/recovery stops new authority. Virtual
faults stay precise on the original path. A physical post-ACK RAM error
violates the existing successful-RAM premise: keep responsibility and report
failure. An errored refill waits for already held successful output offers to
finish instead of withdrawing them; new successful offers stop before error
capture. No success drain follows captured failure.

For actual cache wiring, keep one Scala Mem.write site per tag way/data bank.
Select posted/ordinary payload and enable ahead of the existing write site;
a mutually exclusive second write call still changes FIRRTL port shape.
Preserve original MSHR/acquire/source counts.

## Evidence and remaining gates

The byte oracle samples memory at real coherence grant ownership. Before-A
DMA changes untouched refill bytes; after-install DMA survives held ACK/drain.
Checks cover grant/E sequencing, response-ticket reuse, two-owner ordering,
byte overlaps, clean/dirty victims, full WB completion, proof/context/token
mutations, held offers, finite generation fallback, continuing cohorts and
responsibility handoff. Host schedules are synthetic component cases.

The three PostedStoreMergeRebuildSpec checks passed on the frozen source.
Disabled owner CHIRRTL contains no registers, and the enabled interface
elaborates. The actual scalar GSIM owner fixtures passed as detailed below.
The next gates are real cache/home observations, actual CPU lineage and
precise fault/order tests, then fresh identical-guest A/B and resource/port
census. No synthesis result or whole-design OFF pruning is claimed.

## Source-only fixture follow-up

The immutable first checkpoint is local commit
ab11f64ff4e6ad1279465b7f6c8a009a02108570. The following fixture is a new commit,
not a retroactive qualification of that checkpoint.

PostedStoreMergeGsimMain requires an explicit generation width of 64 or 2.
Every refill/install beat is a separate scalar UInt(64); no generated array ABI
is assumed. ports.py emits mechanical scalar accessors, while fixture.py
supplies authored full tokens, contexts, byte intent and event schedules and
checks raw observed words through contract_oracle.py. Three transport-only
host checks exercise C++ generation against a scalar stub, full uint64 values,
unknown-port rejection and Python syntax. The stub is not an RTL model.

The actual component runs passed eight positive generation64 scenarios and
eleven negative actual RTL assertions, plus a separate generation2 model for
finite exhaustion, held fallback and changing cache-admission decisions.
Cases include two line owners with reversed refill order/oldest installation,
five responses before refill with reused tickets, held install/drain/release,
before-A base mutation, clean/dirty/cancelled victim lifetime, post-install DMA
under held ACK, continuing and ending cohorts, and an error blocked behind a
held successful install. Negative cases corrupt owner generations, ACK tokens,
refill identity, WB tickets, held context/payload and cancellation/episode
preconditions. Each negative required the expected RTL assertion diagnostic
and failing model exit; a sanitizer error could not count as success.

After a parent-granted heavy slot, source the recovered activation script and
run the single frozen gate:

    python3 simulator/gsim/posted_merge_rebuild/run_component.py --slot-granted --output NEW_ATTEMPT_DIRECTORY

The runner requires a clean committed source and verifies installed pinned
tool receipts, source hashes, fresh output, a 200 MiB artifact budget and a
700 MiB free-space floor. It runs the three Scala/config/elaboration checks,
one generation64 and one distinct generation2 model, sanitizer builds, raw
trace checks and expected assertion negatives. It never calls generic setup
or rebuilds tools. Per-step budgets are 15 minutes for first compile/config,
5 minutes for emit/generate, 10 minutes per native translation unit and
3 minutes for each model's cases. These are safety bounds, not measured costs.
The first coherent run completed all steps in 124.76 seconds, including
81.64 seconds for first Scala compilation/config/elaboration. The entire
attempt was 10,783,765 bytes; no guard fired. This is a tool-run duration,
not a hardware performance measurement. The observed positive schedules
were 12 to 43 cycles each; negative schedules terminated on their precise
assertions. Preserve the full source/model/log/receipt package to replay the
proof premises and raw observations. The qualification commit changes only
documentation and adds this result record; its executable sources match the
frozen source named above.
