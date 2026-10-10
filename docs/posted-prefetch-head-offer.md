# Staged posted head offer during autonomous prefetch

> Historical candidate design notes. Current integration identity, distinct entry points,
> fresh checks and explicit coverage scope are in [posted-prefetch-integration.md](posted-prefetch-integration.md).

This generic default-OFF option is selected by `postedPrefetchHeadOffer` or
`--posted-prefetch-head-offer`. It requires posted stores, next-line PF,
registered memory addresses and non-fast store retirement. FPGA-next and the
complete machine assembly also require cache posted/PF coexistence. Read-only
PF is legal; store-origin PF remains its own independent option.

## Exact producer predicate

The existing `postedEligible` retains the true ROB head and full token, ordinary
aligned guaranteed-RAM integer store, original physical address, no active
translation, no atomic and successful PMP. Existing commit, exception, recovery,
FP/context, serial-LSU, staged payload and ready checks remain in the start path.

For an initial eligible staged offer with no live posted responsibility:

```
cpuAcceptedMemoryBusy = integerMemoryBusy || fpMemoryBusy || postedBusy
OFF: require !memoryBusy
ON:  require !cpuAcceptedMemoryBusy
memoryBusy = cpuAcceptedMemoryBusy || externalPrefetchBusy
```

The FP term exists in FP-enabled assemblies; otherwise it is false. Integer busy
includes LSU response/completion owners and the StoreBuffer. Posted busy includes
the CPU count and externally owned cache/fallback work. The new wire is elaborated
only when enabled and depends on accepted ownership, never the current offer,
READY, fire, aggregate drain or a cache classification. No register, proof bit,
queue, response credit, owner, MSHR or cache resource is added.

The original initial-start assertion remains verbatim when OFF. When ON it is
replaced by assertions that the start is the staged proof-bearing start, the
integer/FP/posted accepted owners are empty, and any remaining `memoryBusy` is
positively attributed to `externalPrefetchBusy`. Fast direct retirement is an
illegal ON configuration and its original gate remains unchanged.

## Unchanged ownership boundaries

Only the initial eligible staged producer offer changes. Additional posted
members, proof-free loads/stores, atomics, fences, system/context transitions,
interrupts and recovery retain their existing gates. `memoryBusy` and aggregate
drain retain their complete PF-inclusive meaning. Proof capture, full-token
transport, StoreBuffer local ACK, checked enqueue and response ownership are
unchanged. A local store ACK still does not mean downstream coherence completion.

The cache may accept a legal resident legacy hit using its existing safety checks.
A cold new posted owner or generation-exhausted fallback still waits for its
unchanged response/MSHR/WB/PF, maintenance and coherence conditions. This option
grants no cache permission or ACK authority and changes no PF tail lifetime.

## Scope and qualification

The historical original COPY19 comparison reported 124,921 PF-only initial-head
blocked cycles across 2,015 exact tokens, all resident stores, with the full tokens
followed to launch. Its totals were 457,146 posted/PF-coexist cycles, 452,641
posted/PF-excluded cycles and 383,603 no-posted cycles. These motivate this isolated
experiment; they are not predicted saved cycles or fresh qualification. That historical pre-integration snapshot had incomplete recovered runtime evidence
and an unexplained terminal reverify failure; it is not used as a passing gate.
The later fresh scoped closure and original-guest A/B are recorded in
[the current preset record](posted-performance-preset.md), which explicitly
preserves the two UNREACHED cases and the historical COPY regression.

The intended capacity and maximum launch rate remain unchanged. ON may advance
the first eligible staged offer while PF alone owns memory, but may simply move
its wait to the cache. Cycle benefit, native comparisons and bounded runtime correctness now have
separate evidence in the current preset record. Logic/area/timing cost and routed/
physical-board behavior remain unqualified. Required directed coverage includes PF pending/live/release tails,
concurrent integer/FP/posted owners, genuine head/full-token authority, immutable
held proof, resident hit versus cold/fallback exclusion, response/ACK stalls and
strong context/recovery boundaries. Independent CPU/cache fixtures own this proof;
host selection tests alone are not hardware evidence.

Host selection: `python -B -m unittest discover -s simulator/gsim/posted_prefetch_head_offer -v`.
Pure Scala configuration: `mill -i IonSoC.test.testOnly ooo.PostedPrefetchHeadOfferConfigSpec`.
Heavy qualification must use a coordinated frozen source/profile checkpoint.
