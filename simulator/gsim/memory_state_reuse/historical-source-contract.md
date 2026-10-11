# Memory state reuse candidates

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

The declaration upper bound is 4,416 scalar bits for this option, or 4,800 for
both at ROB64. Actual native state and mapped resources remain unmeasured.

`MemoryStateReuseGsimMain <output> <off|on> <off|on>` prepares the existing exact
ROB64/PRF64/LSU4 frontier+LRU+posted-priority focused fixture for all four resource
combinations. The arguments select index reconstruction then address sharing.
Its default historical priority entry remains unchanged; outputs preserve the
existing full-token probes. This selector has not been elaborated or executed.

## Verification status

Only source review and small host/configuration checks are currently authorized.
The Python contract tests establish host algebra, full-width stale-tag rejection,
and source consumption boundaries; they do not execute the DUT. Scala specs are
prepared but not run. Native actual-state delta, exact default-OFF native equality,
focused execution and limited affected same-guest CPU checks remain mandatory.
No GSIM model build/run, native elaboration, synthesis, physical timing, or board
qualification is claimed.

Pending acceptance gates, in order:

1. Compile the coherent batch once and run the prepared pure configuration specs.
2. Emit actual native OFF, index-only, address-only and combined profiles. Compare
   OFF against the published-equivalent baseline without normalizing RTL; prove
   the intended groups disappear and all 64-bit tags/ports/geometry remain.
3. Run focused actual-DUT stale/high-tag, held-owner, kill/reuse/wrap and
   B/H/W/D, atomics, canonical/virtual, misalignment/error cases. Include two
   late store preparations plus a distinct-row load start, and a rejecting
   unconditional shared-write negative. Existing host algebra is not this gate.
4. Bind new candidate-local ON observer ABI to actual model receipts before
   limited affected same-guest CPU/NEMU checks. Do not reuse old runtime evidence.

Prepared host commands:

```sh
python3 -B simulator/gsim/test_memory_state_reuse_cli.py
python3 -B simulator/gsim/memory_state_reuse/test_contract.py
python3 -B simulator/gsim/memory_state_reuse/test_address_lifecycle.py
```
