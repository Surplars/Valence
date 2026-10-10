# Posted-store delivery integration review

The optional posted-store path now has actual CPU→cache→coherent-home→AXI
qualification, including the correction for a premature preparation-induced
seal. Both `postedStoreMerge` and `translatedResponseEmptyFlow` remain default
`false`. The original Bare WRITE benchmark improves, while Bare COPY regresses;
the measured tradeoff is recorded in [the performance report](posted-store-seal-performance.md).
The complete tested activation is in [the usage instructions](posted-store-seal-performance.md#activation-and-default);
the COPY regression does not support general-purpose enabling. This local source
collection is prepared for review and is not a publication receipt.

## Published base and preserved source

The local base is `e4e0a9e0994c5776e1286368b3f4f47e25626c28`, tree
`5e963223bda2acb0acfc0b6bafe8c2af650ce631`, independently checked byte-for-byte
against published dev `ccf130cd0c79ef582186d2165da1273b72fc94f7`.
The local Git transport did not provide that remote commit object. The publication
owner must use the actual remote commit as its compare-and-swap parent and
recheck dev before publishing the complete tree delta. No main update is intended.

All fifteen published standalone-owner files are byte-identical to that base.
All twenty-five published translated-response paths remain present. Its
DataResponseBuffer, behavioral fixtures, independent ledger and historical
results remain byte-identical. Shared configuration, CLI, assembly and docs
retain the published selector through explicit additive integration. The final
review packet records all original and candidate blobs, modes and SHA256 values.
Both-options-ON CLI routing tests are not hardware qualification of that combination.

The original cache/CPU integration was imported from `bc518ec83fc51bbef9e5376f9cee0e1e10200848`,
with cache docs through `b8539097f8073b04248b3e49aac0c6f68af7e342`, real-home
tests through `970934beb284fbb8b20cf718853c42c63e859392`, and CPU lineage tests
through `e20b6589741ffbf410d01921eef1e9cd0a7a1d40`. Shared entrypoint merge
resolutions retain every existing prerequisite and both OFF defaults.

## Actual source and qualification mapping

The executed corrected model source is
`0658f2d4a543ba5849498af626eec0a248363540`, tree
`cc1d50b223fc0b6ebec448292ce8964986b56af2`.
The executing directed host is
`4bf50c7ba539590268b74ef28474a96dbb2da878`, tree
`7d4cf4aba8424b314659a29f94e8c0220e652520`.
The subsequent collection `b2538e0e947959763f3ff8d61425b0a1b2cecb4c` adds only
qualification documentation. This delivery update adds documentation and a
machine-readable performance summary and updates one host source-signature
check for the existing passive-probe argument; it does not change model or
executing host bytes.

Only IntegerBackend.scala changed in production relative to the first qualified
DMA4 board source `8f9d08a592ac38d35db66b9d260cf24ad9f28b88`. The change suppresses
sealing for a valid, prepared, still-young, full-token physical naturally aligned
ordinary RAM integer store with current PMP permission. It does not grant head
authority, start a store, manufacture proof or change retirement. All load,
virtual/IO/atomic/unsafe-store and system/recovery/context/interrupt boundaries
retain their sealing behavior. The expression exists only inside the optional
posted interface. See [the causal trace and correction](posted-store-younger-preparation-seal.md).

| Gate | Exact scope and result |
|---|---|
| Published standalone owner and translated response | Original source inventories retained, with their original evidence |
| Actual private cache | Four models, fifteen positive cases, six exact RTL negative cases; explicit CPU authority supplied by fixture |
| Real coherent home | Gen64 OFF/ON, gen2 exhausted fallback and held ReleaseAck; six trace replays and five offline observer mutants |
| Executing CPU lineage | OFF5/ON5 and token/byte controls; actual head/PMP/full-token transport, context and precise faults, synthetic downstream retention |
| Original actual DMA4 CPU/cache/home | Physical stores, masks, two dirty ways/third conflict, ordinary load/FENCE.I, real delayed B and final ReleaseAck; five cases passed |
| Corrected actual CPU/cache/home | Fresh OFF and ON models; 249-instruction, 41-store, 6-load guest; four cold lines each have eight members before install; full memory/owner/drain checks and exact token/byte controls passed |
| Old-source counterexample | Identical directed guest and complete final memory checks; old ON fails the fixed first-line membership witness (1/8/8/8), corrected ON passes (8/8/8/8) |
| Final actual instance audit | Six full core configurations, both DDR objects, three cache concurrency objects and actual TileLink geometry; audit FIR is byte-identical to both corrected model FIR files |
| Original guest performance | Fresh OFF/ON executions of unchanged Bare WRITE18 and COPY19; all original correctness checks and precise trap controls passed |

The corrected OFF graph-reuse attempt was rejected because the actual assertion
message changed its literal source line. The strict comparison was preserved;
OFF was freshly generated and compiled. Neither old objects nor old benchmark
executions are presented as fresh results. The initial DMA1 profile and early
insufficient-coverage guest remain separately scoped; failed coverage attempts
are preserved. Original slow WRITE/COPY outcomes were performance regressions
with passing correctness oracles, and are recorded separately.

The actual profile is RV64GC, issue2, LSU4, D-TLB16/I-TLB8/PTE4, 512-line two-way
64-byte I/D caches, DMA line mode with four entries, two MSHRs/response credits/WB
slots, physical ingress and fetch/history/prefix features enabled, precheck and
prepared stores enabled, store PF/MRU enabled. Both request and translated
response-flow experiments are OFF; fast buffered-store retirement is false.
ROM is 128 KiB, RAM 2 GiB, and the complete normalized constructor and final
instance maps are retained in the audit, rather than inferred from `Selected`.

## Limits and publication handoff

CPU-only Sv39 success/no-proof and precise faults retain their separate source
and environment scope. The new physical board guest does not independently
cover every APLIC, FP/atomic, recovery or context transition. Posted plus
translated-response-flow ON has not been qualified together. Hypervisor context
support, new WB reservations, early owner reclamation, token compaction and
posted/prefetch coexistence are not implemented here.

Default-OFF optional proof/owner ports and state are pruned by the production
option. Fresh OFF runtime and actual-instance audits are complete. The fresh no-probe [native storage audit](posted-store-native-cost.md) adds
9462 declared state bits when ON. These are not synthesis area,
timing or board measurements. There is no new full-workload or physical-board
performance claim.

Publication requires the final raw-tree preservation review and a dev update
against its current remote parent. All executed model, host, tool, guest and
receipt identities remain those listed above and in the accompanying records:
[cache](posted-store-cache-qualification.md), [home](posted-store-home-qualification.md),
[CPU lineage](posted-store-cpu-lineage-qualification.md),
[first board](posted-store-board-lineage-qualification.md),
[corrected board](posted-store-younger-preparation-seal.md), and
[benchmark](posted-store-seal-performance.md).
