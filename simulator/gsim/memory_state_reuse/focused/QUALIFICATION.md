# Memory-state reuse focused qualification, r1

The frozen production/test Scala source is `3969476cad0775f5b6de405502a4e6822f566311` (two independent default-OFF production commits beneath it). No Scala or DUT source changed during this focused run. One combined-ON real PostedPreparationPriorityGsim model was emitted and compiled; no separate four-way model compilation was performed. Native four-way structural results are in the adjacent memory-state-reuse-native-20261011-r1 namespace.

## Actual results

- The existing 26 focused cases pass on combined ON. Their original raw output, including cycle witnesses, retirement and byte digests, and retained-owner counters, is byte-identical to all 26 prior qualified priority-ON outputs. `original-26-output-comparison.json` binds the archive and both hashes for each case. Extra row observations are reported separately.
- `reuse_widths`: 448 accepted/retired instructions; 147,776 row checks; all B/H/W/D load and store widths; all 64 allocation rows; 74 store-to-load and 88 load-to-store owner changes; 60 cycles with two preparation writes and eight with both preparation writes plus an ordinary-load write in another row.
- `reuse_frontier`: the actual final LSU owner differs from the staged memory choice; nine virtual store starts retain their prepared VA despite a distinct canonical/physical value. Seven dual-store and one three-writer cycles are observed. The independent original PA, bytes, order and full-token oracles pass.
- `reuse_kill`: eight real branch redirects coincide with captured late preparation of a still-pending/live younger store. Each captured write is suppressed; 109 instructions retire and 52 cancel out of 161 accepted, with no killed store start. The raw trace includes rank, slot, full tag and actual write bit.
- Seven DUT-host negative runs reject the intended corruption: original refill data, original LSU full token, retained address payload, tag bit 63, forged second line allocation, frontier payload and virtual-store payload. Exact failure strings are in `qualification-summary.json`; exit status alone is not considered evidence.
- The small independent host oracle test includes positive lifecycle transitions and eight deliberate corruption cases. These host-only tests supplement the actual DUT checks and are not a substitute for them.

The old 26 cases use host-r1. New width and frontier cases were checked again on final host-r4; kill uses host-r4. All seven negative runs use host-r3, whose checked observer and guard code are identical to r4 except the added kill trace and a separate new stimulus function. Archived source directories retain the exact r1/r2/r3 bytes referenced by earlier launch receipts. Every host uses the same combined-ON model object.

## Diagnosed host error, with independent OFF control

The first added same-line byte-store workload failed the historical `ordinary cache allocation reused an outstanding line owner` guard at cycle 271, in both combined ON and the already-qualified OFF model object. No DUT model was rebuilt for that control. The first member was tag 125 / slot 61, accepted at cycle 268; the second was tag 126 / slot 62, PA 0x80200108, line 0x80200100. A source-0 Grant remained at beat 0 and E was low.

The observed second event had `demandMiss=1`, `postedAccepted=1`, `newLine=0`. The production cache observation `demandAlloc = cpuFire && needsMissSlot` also fires for posted joins. The actual allocation path creates a posted MSHR only for `accepted.newLine`. The historical host therefore misclassified a legal retained-line join as a fresh allocation.

The candidate-local host now uses `demandMiss && !postedAccepted` for ordinary allocations and `postedAccepted && newLine` for posted allocations. The original duplicate-line guard is unchanged for those allocations. Joins additionally require the complete original retained context/reservation and an outstanding line whose original full-token member belongs to that retained owner. Deliberately treating the join as a new allocation still triggers the original guard. The same unmodified instruction stream then passes on OFF and ON with the same phase and retirement cycles. Both failures, exact old source bytes, control object/header hashes, and successful control receipts are preserved.

## Lifecycle and ABI limits

The queue index is reconstructed only under explicit ON profile and exact ROB64 geometry. Tags remain raw 64-bit values. Captured, LSU, rename, completion and retirement tokens retain their original index plus full tag. Unknown layouts fail closed; no other payload is used as a missing-field substitute.

The shared load writer is observed only on the final accepted ordinary LSU load, excluding store and atomic. Prepared-store write grants and independent accepted instruction intents determine expected VA and lane data. Address rows are checked on the following physical state edge, including held rows, killed captures, allocation reuse and concurrent different-row writes. Invalid/noncanonical serial-load replay payload is not treated as authority.

A same-row old-owner retirement plus new allocation on one edge is structurally unavailable: RenameRob admits using the old count (without borrowing retiring capacity), and allocationPrefix is false during recovery. The monitor rejects any such overlap; real distinct-row retirement/allocation overlap and subsequent same-row generation reuse are exercised. Late preparation kill is exercised directly. Stale full-token stage reuse is covered by the original `token_reuse` case; no claim is made that a stale captured preparation persists through a prohibited recovery/allocation edge.

For full-board CPU observers, ON queue index decoding must be slot i with a profile/geometry guard. Removed `loadBeat/loadLanes` may be decoded from `storeAddress >> 3` and `storeByteLanes` only under the original ordinary-load replay validity/class/canonical gates. A store retains full VA64 and lanes8. Historical 16-row cpu_order_replay adapters are not valid ROB64 decoders. Full-board same-guest performance/transaction qualification remains a separate pending gate.

## Reproduction and bindings

The external execution namespace is `memory-state-reuse-focused-20261011-r1` beside the immutable source and native namespaces. The tracked fixture files are exact copies of the files used there; run the stage scripts from a materialized external namespace with these same relative dependencies. `run_step.py` validates source, compiled class directories, native runtime binding and tools before each stage. It enforces one granted slot, 1,800 seconds for model Clang, a 700 MiB disk floor and bounded logs. `run_matrix.py` binds the actual linked binary/header/profile and source bytes for every launch.

The single model Clang compile took 320.357 seconds and peaked at 6,350,764 KiB process-tree RSS. Elaboration took 6.007 seconds / 614,692 KiB; GSIM generation 39.035 seconds / 3,663,096 KiB. Host-only links were about 11-12 seconds and 360 MiB. No Vivado, synthesis, mapped-area, timing, or CPU-performance claim follows from this focused gate.
