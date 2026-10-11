# Memory state reuse candidates

Current status: **PASS_NATIVE_FOCUSED_MODEL_GC_CPU19_CPU21**. See the
[current integration evidence](../../../docs/experiments/memory-state-reuse.md)
and [reproduction boundaries](REPRODUCTION.md). Both flags remain default OFF;
recommended presets are unchanged. Historical source/test snapshots retain their
original provenance. No new-checkout test or DUT run is claimed.


Source baseline: `0da2a2258a202f911a1f2ad7a1dd6ed18098a5af`, tree
`7cca8ba3f646732120fd29c3206bd07fb68b9359` (published-equivalent be675).
No baseline or recommended preset changes. Every option defaults OFF.

## Fixed queue index

`reconstructIssueTokenIndex` / `--reconstruct-issue-token-index` keeps the
queue's full generation tag and reconstructs the fixed row index before every
one-hot or dynamic consumer. The only queue writer targets the accepted rename
index and rows never move. The stored index field is tied to zero at its only
writer, following the existing unused immutable-payload convention. It is not
an owner token. OFF uses the original register directly through a Scala alias.

All captures, stale-completion checks, retirement/recovery admission, epochs,
PMP and error paths retain their existing full-token and validity checks. An
unallocated row's newly defined static index does not authorize its undefined
tag. The declared upper bound is 384 scalar bits at ROB64, not a mapped result.

The active `PostedPreparationPriorityGsim` token probe reads the authoritative
view. Historical source snapshots are untouched. Existing C++ host consumers
of `queue$$renamed$$token$$index` need a new, explicitly bound ON layout before
using this candidate: `fixtures/monitor_bandwidth_fetch_prefix_v2/stage_adapter.h`,
`monitor_bandwidth_fetch_history_v1/stage_adapter.h`,
`monitor_bandwidth_replay_lsu4_v2/stage_adapter.h`, and the `cpu_order_replay` /
`cpu_order_replay_history_v1` drivers and ABI validators. A new ON adapter must
require the actual profile flag and exact geometry, reconstruct only the slot
index, retain the full stored tag and every live/valid condition, and cross-check
against independently observed accepted-rename tokens. Missing fields must not
trigger a generic fallback. Existing OFF layouts remain the acceptance baseline.

## Shared load/store address state

`sharedMemoryAddressState` / `--shared-memory-address-state` independently retains
the original 64-bit store address and 8-bit lanes per row. An ordinary issued
load uses that row's upper 61 bits and lanes for replay. The original load bank
was written on every accepted LSU start, even for stores and atomics, but replay
never observes those excluded classes. ON therefore writes the shared row only
when the final accepted LSU request has both store and atomic false. This also
handles the independent frontier-selected load. Store starts leave their full
prepared virtual address intact, including its low three bits. Load writes set
those unobserved low bits to zero. Canonical-store/PMP authority is not shared.

The non-early per-lane preparation writes and the two early captured-owner
writes retain their exact grants, data, full-token revalidation and source order.
An accepted load and two previous-cycle prepared stores may write three distinct
rows in one cycle; there is no arbitration, added state, read port or cycle.
Assertion-only per-row write witnesses reject duplicate preparation ranks and
store/load same-row conflicts. The registered orderCheck beat/lanes remain
separate. Both options are legal independently; neither needs a new prerequisite.

Lifecycle boundaries:

- Queue class changes only on accepted allocation; full token tags never narrow.
- Kill and retirement clear memoryLive, canonical and store preparation validity.
- Early preparation checks pending, memoryLive, kill and the complete captured
  token before writing. A same-edge store start and late store preparation may
  coexist because the shared load writer excludes that store.
- Allocation remains last for validity/class updates. Old bits left in a reused
  row cannot become store-known or canonical-load authority for its new token.
- Misaligned/faulting loads preserve the original beat/lane values; existing
  replay eligibility and fault handling govern their use. Atomics never become
  ordinary-load replay payloads.

Actual native lowering removes 4,416 scalar bits for this option: 69 bits per
ROB64 row (loadBeat61 plus loadLanes8), or 4,800 bits with fixed-index reuse.
The combined backend scalar reduction is 19.143%; the reachable production scalar
reduction is 3.756%. Arrays and RAM ports are unchanged. The existing shared row
gains an ordinary-load write source (two to three alternatives); mapped resources
and physical timing remain unmeasured.

`MemoryStateReuseGsimMain <output> <off|on> <off|on>` prepares the existing exact
ROB64/PRF64/LSU4 frontier+LRU+posted-priority focused fixture for all four resource
combinations. The arguments select index reconstruction then address sharing.
Its default historical priority entry remains unchanged; outputs preserve the
existing full-token probes. The actual joint-ON focused model has been qualified;
the native four-mode census separately measures each independent option.

## Verification status

The actual native four-mode gate and 22 pure configuration checks passed against
frozen source `3969476`. Joint-ON focused qualification passes the original 26 cases
with byte-identical original outputs, three directed cases and seven intended
nonzero controls. [Focused qualification](focused/QUALIFICATION.md) preserves the
initial FAIL and the candidate-local retained-line join/allocation correction.
The duplicate-new-owner guard and independent join-context checks remain active.

The official 17-TU Board model, full ABI/layout checks and original RV64GC positive
(33018 cycles)/negative gate passed. Case 19 passes with exact original stdout/all 18 raw streams and its trap control.
Case 21 also passes at 345578/5565, with exact original stdout/all 18 raw streams
and its original trap negative. The fresh retry followed a preserved output-budget
stop and reused the same tested model/host.
Kernel/flush cycles are 380840/5572 and 345578/5565 respectively. All original
guest/buffer/fault/owner oracles, stdout and 18 raw stream identities are closed.

Only the explicit ROB64/PRF64/LSU4/D16/DMA4 profile is qualified so far. No R16,
full-suite, mapped-resource, STA, routed-timing or board-throughput claim follows.
The historical cross-interval boundary join remains UNKNOWN.

Portable host commands and bound native/focused/CPU workflows are documented in
[REPRODUCTION.md](REPRODUCTION.md). The preserved execution scripts require their
original external layout or an explicit new binding and fresh receipts. Their
presence in this new integration checkout is not evidence they ran here.
