# Default-OFF memory-state reuse

Status: **PASS_NATIVE_FOCUSED_MODEL_GC_CPU19_CPU21**. The scoped resource
qualification is closed. Both options default false, and the recommended
performance presets are byte-for-byte unchanged. The only tested explicit profile
is ROB64 / PRF64 / LSU4 / data-TLB16 / DMA4 with the existing frontier, LRU and
posted-preparation-priority configuration. No R16 qualification is claimed.

## Change and ownership contract

`reconstructIssueTokenIndex` (`--reconstruct-issue-token-index`) reconstructs each
fixed queue slot's index at every semantic consumer. Full 64-bit generation tags,
captured tokens, live/kill/epoch checks and all non-queue owner tokens remain.
`sharedMemoryAddressState` (`--shared-memory-address-state`) reuses the existing
store VA64/lanes8 row for ordinary-load replay metadata. Only the final accepted
non-store, non-atomic LSU load writes the load interpretation. Store preparations
retain their source order, grants and full-token revalidation; stores retain the
full virtual address even when canonical/physical addresses differ. The independent
registered order-check state remains. The changes can be selected independently.
See the [source contract](../../simulator/gsim/memory_state_reuse/README.md).

The publication base is remote dev `be675abe7e4e0e374d2e5f5c42f53ddab64c3d91`, tree
`7cca8ba3f646732120fd29c3206bd07fb68b9359`. Local `0da2a2258a202f911a1f2ad7a1dd6ed18098a5af`
is its exact tree equivalent, not the same commit. The two production review units
are `2a2a3c8` and `4d3f1b5`; compiled source is `3969476`, and test-only additions
include the retry wrapper at `cc8ac594` (historical source snapshot `8d9bc67`). Integration documentation does not change the frozen source or out.

## Established evidence

| Index/address flags | Backend scalar bits | Delta from OFF/OFF |
|---|---:|---:|
| OFF/OFF | 25,074 | 0 |
| ON/OFF | 24,690 | -384 |
| OFF/ON | 20,658 | -4,416 |
| ON/ON | 20,274 | -4,800 |

The address reduction is 69 bits per row (61-bit aligned load beat plus 8 lanes),
not 72 bits per row. Combined savings are 19.143% of backend scalar state and
3.756% of reachable production scalar state. The shared address row gains a third
write alternative alongside the two existing preparation sources.

These are reachable declared scalar bits after native lowering, not mapped FF/LUT
or timing results. All 4,096 queue-tag bits, 100 RAM helpers/ports/geometries and
484 hierarchy instances remain. No scalar registers are added or widened; only
IntegerBackend.sv changes. OFF/OFF matches all 275 historical native raw files,
including the filelist. [Native details](../../simulator/gsim/memory_state_reuse/native/README.md)
retain the added ordinary-load write selection cost and measurement limits.

The joint-ON actual focused model passes the original 26 cases with byte-identical
original output, three new directed cases and seven intended nonzero controls.
Coverage includes B/H/W/D load/store widths, all 64 allocation slots, high/full-tag
reuse, two preparation writers plus a distinct-row ordinary load, final frontier
selection, distinct virtual-store VA/PA, actual late-preparation kill, held state,
atomic exclusion and fault/IRQ/context behavior. Same-row retirement/reallocation
on one edge is prohibited by the original admission/recovery logic; its exclusion
is checked. Distinct-row overlap and later same-row reuse are exercised.

The original monolithic Board compile ended at signal 9; its cause remains unknown
(OOM suspected, unproven). Official GSIM `--cpp-max-size-KB=4096` generated 17 TUs
from the same frozen FIR. Serial compilation kept `-std=c++20 -O1 -g
-fsanitize=address,undefined -fno-sanitize-recover=all`. All 17,501 state-member
layouts match the original header, with sizeof 305,776 and alignment 8. Only
subStep1 through subStep16 method declarations were added. The official RV64GC
positive passed at 33,018 cycles and the intended independent negative exited 1.
Case 19 also passed at 380840 kernel / 5572 flush cycles, with both original
stdout streams, all 18 original raw sidecars and the original trap control exact.
Case 21 also passed at 345578 kernel / 5565 flush cycles, with all 18 original
raw sidecars, both stdout streams and the complete primary result exact; its
original trap negative passed. The first attempt stopped at an undersized output
budget before a DUT/oracle result. Its preserved partial output is infrastructure
history; the fresh retry reused the same model and changed only the output budget.

## Preserved initial FAIL and observer correction

The first same-line byte-store workload failed the historical duplicate-line-owner
guard at cycle 271 in both joint ON and an already-qualified OFF model. The second
event had `demandMiss=1`, `postedAccepted=1`, `newLine=0`: a legal retained-line
join was being classified as a new allocation. The candidate-local observer now
classifies ordinary allocation as `demandMiss && !postedAccepted`, posted allocation
as `postedAccepted && newLine`, and separately checks the complete retained
context/reservation plus an existing line member's full token for joins. The
original duplicate-new-owner guard remains, and a forged second allocation still
fails it. The original failure receipts, exact source and OFF control are preserved;
no DUT change was made to accommodate the observer. Full diagnosis and scope:
[focused qualification](../../simulator/gsim/memory_state_reuse/focused/QUALIFICATION.md).

## Closed CPU scope and release limits

Case 19 is closed at 380840 kernel / 5572 flush cycles; case 21 is closed at
345578 / 5565. Both retain the original guest/buffer/fault/owner oracles, stdout
and all 18 original raw sidecar digests, including trap controls. The complete
primary result was reparsed. Exact raw/stdout identity and unchanged parser bytes
allow reuse of the original full-parser certificates; no forced full-parser
rerun is claimed.
Any mismatch requires the full original parser and explanation and blocks an
unqualified equivalence claim. The historical cross-interval boundary join remains
UNKNOWN. No full 54-case rerun, R16, Vivado, mapped resources, STA, FPGA timing,
board throughput, fresh-checkout DUT execution or CI PASS is claimed.

The [machine-readable evidence index](memory-state-reuse-evidence.json) pins the
historical evidence without copying models, binaries or raw traces into Git.
[Reproduction](../../simulator/gsim/memory_state_reuse/REPRODUCTION.md) distinguishes
portable host checks from the historical bound DUT workflows. The source-only materializer reuses 39 existing exact baseline inputs, avoiding
263,604 duplicate bytes. Its 99 reconstructed inputs match all 89 historical
changed files plus ten native sources; hash/path/occupied-output controls reject.
This is preparation coverage, not new hardware evidence. Both original-case
terminal receipts are reviewed and pinned. Generic defaults and recommended
presets stay OFF. Publication uses the reviewed source tree and remote base above;
it does not create a new hardware-execution claim for this integration checkout.
