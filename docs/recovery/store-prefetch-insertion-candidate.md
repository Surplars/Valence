# Store-origin prefetch MRU insertion: independent default-OFF candidate

This document preserves the original pre-execution proposal. Later measured
results and the new delivery qualification boundary are recorded in
[the MRU delivery composition](../delivery-mru-integrated-20261009.md).

Base: reconstructed combined d31bbf3afc7fb4fd4e6682a036c382f63d811773. This work does not change that qualified source or its fixtures. The historical lost-volume implementation is not used.

## Measured reason for this experiment

The new source-bound same-kernel Sv39 4-KiB 128-KiB COPY B/C pair reports 633303 versus 633266 kernel ticks, while C issues 2015 additional complete eight-beat reads. Every one of its 2015 store-origin PF installs is observed as a live full-PA/index owner subsequently evicted by the corresponding A-source demand before use. Actual probe/error count is zero. These are functional CPU observations, not a cache synthetic bandwidth number. C also enabled prepared-store lookahead; the two-feature pair does not isolate PF performance. Both original data/exception/ordering and terminal drain oracles passed.

The reported later B-store hit/miss is a chronological association only: the host observer does not rule out an intervening same-PA refill. The stronger claim used here is the witnessed PF install and matching A-demand eviction itself.

## One policy change

`CoherentCacheConcurrency.storePrefetchMruInsertion` and `--store-prefetch-mru-insertion` are separately default OFF and require checked-store prefetch. On a successful PF refill only, the captured live `storePrefetchOwner(fillMshr)` chooses MRU insertion. Read-origin PF continues to insert LRU. Demand fills/hits keep their original updates. No candidate-time/current-request/write-request inference supplies origin; PF requests remain reads.

Ways=1 remains legal and unchanged because it has no replacement register. PF still rejects MSHR=1 under its existing requirement; default-OFF capacities 1/2/4 and ways 1/2 retain the old paths. ON is tested for the existing legal MSHR=2/4 and independent WB capacities, not restricted silently to the selected 2/2/2 geometry.

The change only writes existing replacement metadata. It adds no request, response, permission, admission, drain or coherence state. The already present per-MSHR origin bits, previously assertion/observer-only in no-bores native output, now become functional in two-way MRU mode. Selected ON may therefore retain two extra state bits; actual native cost remains to be measured. No timing or performance gain is promised. A protected PF may move the conflict onto a dirty alternate victim, so AW/W/C traffic and stalls must be measured too.

## Required gates

1. Independent host origin/replacement oracle and hostile controls; Python selector negatives; actual configuration elaboration across the legal boundaries.
2. New real cache/home models with checked-store PF ON on both sides and only insertion different. Preserve the original four byte/protocol/dirty-C/held-D-E/late-Ack/MSHR-reuse/error/probe/flush scenarios and their negative controls. Add authored two-way store-origin conflict and unchanged read-origin LRU conflict, checking full-PA victims and real hit/miss plus AXI traffic.
3. Same-profile no-bores native OFF/ON state/memory-port comparison; count functional origin state, not observed wrapper state.
4. Only after those gates, same formal guest and strict fresh fullCPU WRITE/COPY A/B. Preserve complete initialisation, kernel bytes, faults, per-case buffers and terminal drain. No stride, loop or memory-driver changes.

The cache fixture reuses the separately identified 81-line passive observation delta from the reconstructed PF gate. Its prior native syntactic bridge to d31 allows only declared combinational renaming and one exact mux expansion; this new candidate still receives new model/source bindings. It is not whole-top formal equivalence.

Status: source and lightweight host preparation only. Scala/elaboration, actual candidate cache models, native resources and CPU performance have not run yet.
