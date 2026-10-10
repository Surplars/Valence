# Default-OFF posted-store / prefetch coexistence candidate

> Historical candidate design notes. Current integration identity, distinct entry points,
> fresh checks and pending scope are in [posted-prefetch-integration.md](posted-prefetch-integration.md).

This source candidate starts at `0658f2d4a543ba5849498af626eec0a248363540`
(the narrow younger-store seal correction). It is a new local namespace and
inherits no dynamic PASS. The candidate is not a PPA, STA, board, CPU throughput,
or architectural qualification claim.

## Intended behavior and unchanged resources

`postedPrefetchCoexistence` defaults to false in both
`CoherentCacheConcurrency` and `FpgaNextConfig`. The explicit CLI option is
`--posted-prefetch-coexistence`; it requires `--posted-store-merge`.
The cache additionally requires the enabled posted owner, the existing two read
MSHRs, and next-line prefetch. Checked store prefetch is independently selected;
a read-only prefetch configuration remains legal. Response, MSHR, writeback,
store-member, cache geometry, AXI, DDR, and CPU dimensions do not change.

The throughput target is restoration of the existing at-most-one pending PF
candidate and existing PF miss owner in empty posted-work windows. The change
adds no new port, queue, owner or response credit. It does not add a pipeline
stage to accepted legacy hits. A held new-owner or fallback offer can cancel a
pending candidate and wait until a later edge; genuine PF/ReleaseAck backpressure
can extend that wait until the original obligations drain. This is a policy
opportunity target, not a measured cycle reduction.

The baseline treats retained posted cohort identity and any proof-bearing offer
as reasons to suppress prefetch. Cohort identity can outlive all accepted work.
A checked store hitting a resident cache line uses the legacy hit pipeline and
does not create a posted owner. With this policy ON, the existing prefetch
prediction/allocation rules may run in those otherwise idle windows.

Three prefetch control gates change: sequential read candidate creation, checked
store-history candidate availability, and candidate allocation. Their shared
ON predicate is:

    !postedBusy && (!postedIntent || postedLegacyHit)

Here `postedIntent` means upstream VALID with proof VALID.
`postedLegacyHit` requires owner eligibility, a nonexhausted owner generator,
and `writeHit` (ordinary/cacheable, resident, write). Any other proof-bearing
offer conservatively blocks prefetch, including ineligible or malformed proof.
The accepted request is still the only source of new prediction history; merely
offering a blocked request does not generate a candidate. The OFF predicate
remains exactly `!postedEpoch && !postedIntent`.

## Responsibility and drain audit

`postedBusy` includes both the owner module's busy output and the cache's
`fallbackDrainActive`. Owner busy is `anyLive || count != 0 || fallbackPending ||
failed`. A posted line cannot release until it is installed, all its members
have drained, and its exact victim has completed. Member drain requires its
original CPU response acknowledgement. Consequently early CPU replies and victim
ReleaseAck responsibility cannot vanish merely because one part completes.

The exhaustion fallback sets a separate drain obligation on acceptance. That
obligation remains until owner work, CPU response tickets, MSHRs, writebacks,
eviction/bypass/probe state, accepted prefetch work, and line-acquire engine
response/A/E state are clear. Cohort identity alone is not work; a fallback tail
is work. A live fallback tail therefore never becomes a prefetch opportunity.
Ordinary legacy response tickets remain handled by the original admission
`legacyResponsesClear` predicate; the candidate does not give those tickets
posted identity or discard them.

The platform independently connects `cache.prefetchBusy` to the core's external
prefetch-busy input. Its original accepted-token assertion requires the CPU
memory owner on candidate creation, including the acceptance edge. Mapped-core
aggregate drain requires `!core.memoryBusy`, and flush completion requires PF
empty. Thus ending posted cohort identity cannot cancel or hide PF work. These
wires and assertions are unchanged; a later executing-CPU gate must retain them.

## Necessary exhaustion-fallback readiness guard

The policy also adds `maintenanceReady` to fallback READY only when ON. OFF
retains `legacyReady && !postedBusy`. This is necessary because the original
legacy resident-store-hit path can overlap an accepted prefetch via
`prefetchOnlyHit`. Restoring prefetch after generation exhaustion makes that
state reachable for a fallback offer; accepting it without maintenance clearance
would violate the owner's existing `cacheAdmission.responseAvailable` contract.
The added gate requires the original full legacy response/MSHR/WB/PF boundary
before the fallback fire. It changes no fallback data, token, acknowledgement or
error contract. It adds no state and no READY dependency. Focused cases must show
an exhausted proof-bearing resident hit held across live PF and held ReleaseAck,
then exactly one fallback fire/response and complete final tail reclamation.

## Same-edge priority and absence of a READY loop

The permission predicate depends on registered owner/cache state, upstream
VALID/proof payload, and ordinary resident-hit classification. Owner eligibility
reads proof/request bits and the failure register; it does not consume READY.
Neither `cpuFire`, posted accepted/fallback fire, nor downstream READY feeds this
permission predicate. The banked tag selector retains its existing B/flush
priority, whose B readiness is independent of tag results.

A pending prefetch candidate contributes to pre-edge `prefetchBusy`. New posted
admission still requires `!prefetchBusy`, along with complete legacy MSHR,
response, writeback, and engine/maintenance availability. If a proof-bearing
new-owner or fallback offer arrives beside a candidate, the offer blocks PF
allocation and the candidate cancels. The candidate's old busy state also blocks
new posted admission that edge; a later edge may accept after all old work has
drained. Losing this one arbitration cycle is intentional.

An accepted legacy store hit may create a candidate but cannot create a posted
owner. Existing PF allocation also excludes any offered write (`demandMiss`), so
that write cannot compete for a PF allocation on its acceptance edge. Accepted
read candidates similarly cannot create posted ownership. Assertions check that
PF generation/allocation has no posted responsibility or disallowed proof offer,
and that posted admission sees no candidate, PF MSHR or PF writeback owner.
These assertions are design checks, not independent dynamic evidence.

## Combinational cost to measure

The policy introduces no register or new storage/credit slot. In ON hardware it
adds fanout from existing owner eligibility and resident-hit classification into
the prefetch permission cone. The fallback READY path gains the existing
maintenance-clear cone. Native export/resource comparison must measure their
real implementation after dead-code elimination. Source-level absence of new
state is not a zero-area or zero-timing-cost claim. OFF source/FIR names need not
be byte-identical to the prior source; use a fresh OFF model and actual native
structure rather than asserting graph identity from source intent.

## Scope of verification

Host selection tests exercise both production Python CLIs and both Scala option
entry points, defaults, dependency failures, profile separation, and no output
creation in preflight. The focused Scala spec is source/elaboration only.
The new cache fixture uses a new top/model binding and reruns independent
full-token, full-generation, response-credit and final-byte oracles. It must
observe actual accepted legacy store/read candidates, cancellation beside held
new-owner/ineligible/fallback offers, live PF and delayed ReleaseAck drain,
probe/backpressure, partial writes, exhaustion, and PF failure followed by a
precise demand error. Seal/endEpisode/context cases at this cache boundary prove
only cache-side prerequisites for fences and recovery; executing CPU behavior
requires the separate board/CPU gate.

Final whole-line PMP/read/PBMT/page permission, original head-store authority,
virtual precise faults, actual probes, byte merging, PF error handling, WB lineage,
response credits, load ordering boundaries, seal classification and early posted
ACK/error contracts are unchanged. Original same-guest COPY/WRITE A/B and native
resource cost remain required before any new efficiency claim. Physical DDR
behavior, routed timing and board operation remain unmeasured.

## Host selector correction inherited from the baseline

The original `posted_cpu/test_selection.py` expected the source signature
`def build(c: FpgaNextConfig): BoardSocGsim`, although the baseline builder already
had the optional `lineageProbes: Boolean = false` argument. The first fresh host
run observed one failure in six tests on this stale string assertion. This
candidate updates only that expected signature; the next actual run passed all
six tests. The behavioral/data oracles are unchanged.
