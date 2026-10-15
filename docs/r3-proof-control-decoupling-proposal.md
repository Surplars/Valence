# R3 proof-control dependency cut proposal

Status: source analysis only, based on commit `6fe57114`. No CPU RTL changes,
hardware simulation, synthesis or new physical timing claims are included.
Keep issue2, proof rows3, early credits2 and LSU4. The rejected four-cycle
Route B wait experiment is not part of this proposal.
The actual profile enables `residentMemoryPayloadReuse` and disables
`memoryProofFrontier`. The proposal targets that active resident path; it does
not turn on the separate frontier feature or claim its fixtures cover this path.

## Measured chain and source ownership

The placed report has three setup populations among its first 40 paths:
18 cache-to-proof paths (worst -0.505ns, 37 levels), 19 issue-to-LSU paths
(-0.499ns, 40 levels), and 3 issue-to-address paths (-0.470ns, 31 levels).
These counts include alternate paths to identical endpoints. Route delay is
estimated, accounting for 74–79% of their data delay, not routed signoff.

1. `NonBlockingCoherentLineCache.scala:1037-1070`: registered MSHR phase,
   candidate and captured writeback ownership reduce to `prefetchBusy`.
   `MachinePlatform.scala:464` forwards it through MappedMachineCore,
   MachineCore and IntegerCore to `IntegerBackend.externalPrefetchBusy`.
2. `IntegerBackend.scala:219,319` ORs it into architectural `memoryBusy`.
   `:1964-1968` and `:1997-2015` use that busy in system reservation and
   precise trap eligibility. Keep this architectural drain law intact.
3. `RenameRob.scala:144-197` authorizes head trap/system recovery and computes
   kills; `RedirectTokenQualification.scala` compares full tokens.
   `IntegerBackend.scala:2173-2187,2633-2664` qualifies redirect/completion and
   retirement intent; `RenameRob.scala:286-330` produces actual commit.
4. `IntegerBackend.scala:800-804` merges accepted kill, commit and rename into
   `proofOwnerClear`. That clear reaches proof query/result and row-state
   updates (`PendingVirtualStoreProof.scala:72-82,156,207-212,241-305`).
   The measured cache path terminates at proof-row state CE, not a data output.
5. Separately, `PendingVirtualStoreProof.scala:59-76` dynamically reads the
   indexed current ROB owner and compares full token/VA/size/mask to each row.
   `PendingStoreProofRobMapping.scala` permits index-only distribution ONLY
   because proof.valid already contains that exact same-cycle owner check.
   `IntegerBackend.scala:1252-1286` fans proof/overlap results into per-ROB
   older-store policy and relied-row identity; `:1365-1483` feeds reserve/start.
   This is the observed issue-token -> proof compare -> LSU state chain.

The two chains are coupled by proof lifecycle and authorization. Delaying
`proofOwnerClear`, registering proof.valid alone, narrowing token tags, or
changing the index-only mapping without its premise is unsafe.

## Preferred smallest coherent candidate

Before adding state, qualify one zero-state factoring candidate: the local token
at `IntegerBackend.scala:2161-2162` is selected by `headSystemAccepted`, then
compared in `RedirectTokenQualification.scala:18-22`. Compute full-token equality
against raw system/local/trap payloads in parallel, BEFORE accepted-control
selection, and select Boolean matches with the existing trap/system/local
priority. Do not select 68-bit token payload with a late accepted signal and
then compare it. This is a proposed algebraic refactoring, not an RTL change in
this patch. It may remove the late carry-comparison segment without any cycle
or throughput change; only a later measured candidate can establish its benefit.

Reuse the existing registered memory-address/selection boundary
(`IntegerBackend.scala:780-790,927-1064`). Extend it with immutable proof witnesses
rather than adding a wait counter or a register at every consumer. Pair that
change with row-local lifecycle updates; either change alone leaves the other
measured chain intact. Keep architectural trap/redirect/retirement timing intact.

**A. Separate proof storage cleanup from current-cycle permission.**

Capture owner lifecycle events at the edge as full-token events, with cause,
proof row/incarnation and descriptor/epoch identity where needed. Apply them
locally to proof bookkeeping on the following edge. Do not feed global
accepted-commit/rename/kill masks into every proof-row CE and query-result guard.
This deliberately delays free-row availability by at most one cycle, not
architectural invalidation. Never register an index-only clear: an old event
must not clear a newly allocated token or a reused row.

Before adopting this change, prove the containment law: an owner that becomes
invalid on the current edge cannot issue, bind a new dependent load, publish a
result, or be mistaken for a new owner while its physical row cleanup waits.
Use current registered owner state and raw recovery/context veto at the actual
permission boundary. A result captured into inert storage during cancellation
has no authority until its token/descriptor/epoch is revalidated. If that law
cannot be established for query selection or bind in a case, retain its local
veto and stage that transaction; do not remove the guard for timing convenience.

Admission uses pre-edge free rows; it must not borrow a row merely because a
clear is expected later that cycle. Bound rows are pinned until exact actual
store capture or an architecturally authorized cancellation; epoch change
cannot silently discard a surviving bound-store obligation. Define deterministic
simultaneous event priority and test it; preserve clear/cancel dominance over
result publication and binding even if the storage update moves by one edge.

**B. Stage selected permission evidence, not an unqualified Boolean.**

Compute owner/VA/size/mask matches, older-store coverage and disjointness in
parallel with selection/address preparation. Capture the selected load's full
token, VA/PA/size/mask, epoch, PMP/privilege identity, relied row identities and
their complete store descriptors at the existing boundary. The downstream LSU
offer consumes that registered witness rather than recomputing a three-row by
all-ROB wide owner match plus global policy on its start path.

Keep a narrow final gate for exact selected owner, pending/live class, stable
current authorization epoch, row incarnation/binding, and existing raw
`earlyRecoveryIssueBlock`/pending-exception veto. Do not append the original
global owner scan behind the new register: that merely moves the critical path.
Any reduced check must follow a proved immutable-owner lifetime law, with
independent full-token/descriptor assertions as a reference. Only allocate/store
capture/completion handshakes create or release memory ownership.

The active baseline (`IntegerBackend.scala:1589-1614`) asserts that an offered
LSU start is always ready and reserves/consumes early credit on that same edge.
The smallest candidate retains that contract: a staged witness alone reserves
neither a credit nor memory ownership. While held, it is inert; if a referenced
row is evicted/reused or its current head/readiness policy changes, reject/retry
the witness. At actual start, atomically revalidate, bind relied rows and consume
one exact credit. Pin bound rows for the entire accepted dependent-load lifetime.
Do not stage a Boolean credit.available or rely on a saved head decode.

Only if an independently justified elastic offer buffer is later introduced
should reservation move earlier. That is a separate protocol change: reserve
once per full token, hold payload/witnesses stable, activate only at actual start,
cancel only an unconsumed exact offer, and prove simultaneous consume/cancel and
two-credit/four-LSU capacity. It is not required by the first dependency cut.

Targets before implementation: initiation interval one memory candidate/cycle
when ready, query arbitration one/cycle, no extra steady-state issue/retirement
bubble, and no reduction in accepted transfer duty. Added first-offer latency and
occasional row-reclamation bubbles must be measured; these targets are unproven.

## Risks and alternatives

- Delayed cleanup can add one unavailable-row cycle. Measure three-row occupancy
  and saturated load/store throughput. If it becomes limiting, use a separately
  proved local reclaim reservation rather than combinational late clear bypass.
- A stale witness after SFENCE/PMP/privilege/epoch transition must be rejected.
  A precheck is not permission to issue MMIO, AMO or an architectural store.
- Raw recovery candidates may block a speculative launch conservatively, but
  accepted recovery boundary, inclusive/exclusive behavior, external ties,
  precise exception priority and redirect target remain the existing ledger's
  responsibility. Do not delay CSR/FENCE/trap side effects to hide a path.
- Full-token wrap, row reuse and same-edge rename require explicit ABA/lifetime
  assertions. Do not assume index equality or truncate generation/tag bits.
- A registered busy hint alone is not the chosen cut: sampling busy low and
  allowing new prefetch work on the same edge can violate precise drain. A future
  registered drain-grant protocol would need upstream admission inhibition plus
  acknowledged MSHR/writeback quiescence and has a larger performance surface.
- Registering accepted redirect/commit globally changes retirement/exception
  latency and many contracts. It is broader than the measured proof consumer
  problem and is not the first candidate.

## Required directed regression, after a coherent RTL candidate exists

No new GSIM run is required for this scripts-only patch. For a later RTL change:

1. Extend the independent proof-bank and ROB-owner fixtures
   (`PendingStoreProofGsim`, `ReferencePendingVirtualStoreProof`,
   `R5PendingVirtualStoreProof`, `BoundStorePayloadGsim`) for same-edge result,
   bind, consume, retire, kill and rename; same index/new tag; stale result after
   row reuse; every three-row encoding; delayed cleanup; no false proof authority.
2. Extend `BoundedEarlyLoadCreditGsim` and the active resident backend fixture for two
   reserved credits, consume/cancel races, held offers, stalls, no double credit,
   bound-row pinning and all three relied-row subsets. Frontier fixtures are
   supplementary only if their shared module changes. Use independent expected
   ordering/byte-range laws, not DUT helper predicates.
3. Recovery/control fixtures: older branch versus younger memory offer, replay,
   head trap and system redirect/external tie, inclusive and exclusive rollback,
   IRQ arrival, empty trap, and same-cycle completion/retirement. Check no killed
   memory start or completion reaches architectural state.
4. VM/PMP: SFENCE, PMP permission/privilege changes, stale translation/PMP reply,
   faults/misalignment/VA aliases, MMIO/AMO exclusion and denied operations.
5. One short affected core NEMU/VM suite plus reused-model board smoke, then
   matched mixed memory traffic with accepted requests/transfers per cycle,
   proof/credit/LSU occupancy, reclamation stalls and cycle cost. Preserve issue2
   and the same traffic/service law. Do not treat simulator wall time as speedup.
6. Only after those checks pass, one combined synthesis/place comparison if
   requested. Confirm both measured chains were removed and not recreated at
   final permission, FIFO ready or credit release. Routed/board behavior stays
   explicitly unverified until separately authorized work establishes it.

## Concrete cut boundaries and added-state budgets

All source positions in this section refer to the unchanged `6fe57114` RTL.
These are design bit budgets, not synthesized FF/LUT predictions. Existing
state is subtracted explicitly; candidates are alternatives unless stated.

Width derivation: the reference `actual-core-parameters.json` has ROB16,
tag64, LSU4, proof3, credit2 and PRF48. `OooParams.scala:574` therefore gives
index4. `BackendTypes.scala:6-9` gives token=4+64=68 bits.
`MemoryProofFrontier.scala:7-18` defines MemoryProofPayload=64 VA+64 PA+1 write
+3 size+8 mask=140 bits and MemoryAddressProof=68+32 epoch+140=240 bits.
`VirtualRamLoadPrecheck.scala:31-41` gives a load certificate of
68+64 VA+2 size+64 PA+32 epoch+1 allowed=231 bits, excluding Valid.
These bundle definitions are reused even though the frontier feature is off.

| Candidate | Combinational cut and register location | Estimated NEW state | Acceptance conditions |
| --- | --- | --- | --- |
| C0: prequalified redirect comparisons | Raw registered system/local/trap token payloads -> parallel full equality; late accepted controls select only Boolean results, before retirement intent/commit. Backend:2161-2187; RedirectTokenQualification:18-22; RenameRob:286-330. | 0 bits; extra parallel comparator logic is possible and must be measured. | Exact same-cycle outputs/priority for arbitrary invalid payload, external ties, inclusive head trap, keep=1 system recovery and stale tags. No cycle or duty change. |
| C1: registered lifecycle events | Capture separate source-event slots, then perform row-token matching/cleanup AFTER the register, between Backend:800-804 and proof bank:72-82,241-305. Do not simply register the final per-row clear after all current matching. | Five independent owner-event slots (commit2, rename2, consume1) x (68 token+1 valid)=345; recovery slot 68 token+inclusive+valid+clear-all=71; context epoch32+valid=33; plus three row invalidation bits: total 452. If a distinct event-epoch snapshot is needed, add 32, total 484. Event causes are implicit in slot identity. | No event loss when commit, rename, consume and recovery coincide. Current raw recovery/context and exact owner rules deny permission immediately; deferred freeing changes storage only. No new metadata read port. Old events never clear new owners/rows. Reclamation delay <=1 cycle, measured saturation cost must pass below. |
| C2: witness at EXISTING resident/address boundary | Owner/descriptor/older-store comparisons and range policy are upstream of Backend:925-931 capture; downstream Backend:1274-1296,1419,1477-1486,1589-1614 uses captured evidence plus narrow exact permission gate. | Reuse existing resident token/VA/size. One conservative witness adds valid1+PA64+epoch32+allowed1+privilege2+row-mask3+head-stamp4+row-policy3+3x240 full proof snapshots=830; optional byte mask8 makes 838. A proved immutable-row reference design can avoid 720 snapshot bits, leaving 110..118; that reduction is conditional, not already established. | No authoritative saved head/readiness/credit Boolean. Final validation includes current head policy, exact owner token/class, stable epoch, row identity and raw kill veto. Existing ready-always start and same-edge reserve/consume remain intact. II=1 when ready; no added mandatory wait cycle. |
| C3: optional second elastic offer slot, NOT first candidate | If required after measurement, insert another complete slot at the same boundary, not separate endpoint registers. | Existing resident tuple is valid1+index4+token68+VA64+data64+size2=203 bits (Backend:780-790), already present. A second slot with the conservative C2 witness adds 203+830-1 shared valid=1032, or 1040 with byte mask; add pointer/occupancy control only after choosing an actual queue protocol (roughly 2..4 bits). C2+C3 together add about 1864..1882 bits. | Explicitly revise and independently prove credit reservation/cancel protocol if offers may stall before capture. Preserve two credit owners and four LSU owners, not two additional memory owners. Sustained II=1; no increase of architectural request count or lost/duplicate operations. |

For C1, an event token identifies the immutable owner descriptor already retained
by a proof row; do not add a hidden dynamic ROB/PRF read just to populate an event.
If the immutable-descriptor premise fails, the 452..484-bit design is rejected;
redesign the event payload and update this budget before implementation.
Registering a late 37-level `clearOwners` result merely relocates the endpoint
and is explicitly NOT the intended cut. C0 must also remove the accepted-control
to payload-select to 68-bit comparison feedback before claiming that C1 shortens
the cache-originating prefix. A later timing comparison must inspect both sides
of each new register and the final launch gate.

PMP handling does not require copying the entire state into each offer:
`DataTranslationAdapter.scala:105-131` already registers a 32-bit authorization
epoch and stable flag, detects VM changes and published/raw PMP changes, and
blocks requests during flush/transition. Reuse that contract, retaining the
current context/privilege veto; do not assume epoch equality alone covers a
same-edge change. For comparison, `PhysicalMemoryProtection.scala:7-14` contains
16x(8 cfg+54 addr+65 low+65 end+1 active)=3088 state bits, of which cfg+addr are
992 architectural bits. Duplicating those per offer is not in the C2 budget.

Throughput/correctness gates for any eventual implementation:

- Bit/cycle-exact architectural commit, exception PC/cause/tval, redirect target,
  MMIO/AMO/store order and externally accepted request/response identity against
  an independent model/NEMU; timing of inert proof cleanup may differ only as
  explicitly specified. No generation truncation or oracle changes to match DUT.
- Adversarial event tests cover every pair and meaningful multi-event collision,
  one/two/three rows, same index/new tag, row reuse during stalled witness,
  retirement/backpressure, empty and inclusive recovery, PMP/VM/privilege update,
  and stale positive as well as stale negative precheck replies.
- In a ready, dependency-free synthetic stream, preserve one eligible memory
  offer/query per cycle after fill and issue width2; credit<=2, LSU<=4, proof<=3
  at every cycle. Check that a currently stalled witness never pins extra credit
  or suppresses unrelated eligible issue. No new fixed wait counter is allowed.
- Run matched mixed load/store/cache/PF service traces. Acceptance requires no
  lower steady-state accepted-request/transfer rate and no cycle-count regression
  in the affected short throughput cases. First-offer latency, full-proof-row
  reclamation stalls and worst-case fairness are reported separately. If C1
  cannot meet this gate, retain current lifecycle behavior and pursue C0/C2 or
  redesign reclamation; do not relax the traffic law to hide the loss.
- Short functional gates precede one requested combined physical evaluation.
  A smaller area estimate or an extra register is not evidence of timing benefit;
  verify the old common prefix is absent and no equally long veto/ready path was
  created. No RTL change or such evaluation has been performed by this patch.
