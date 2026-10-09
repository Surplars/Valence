# Store-prefetch insertion: actual cache/home gate

## Status and build identity

Source preparation only, based on the qualified checked-store prefetch driver
at `checked-store-pf-reconstructed/simulator/gsim/checked_store_prefetch/cache.cpp`.
No compiler, generated model, GSIM run or performance qualification was performed
while preparing these two files. Runtime qualification must bind the final
production sources, wrapper, generated model and driver from the same freeze.

- Emitter: `ooo.StorePrefetchInsertionGsimMain out 0|1`
- Generated top/ABI: `CoherentCacheHomeGsim`, unchanged `storePfObs` observation fields
- Driver: `cache.cpp`, `-DCHECKED_STORE_PREFETCH=1 -DSTORE_PF_MRU_ON=0|1`
- The insertion macro must match the emitter mode. It has no implicit default.
  Checked-store PF is always ON; compiling this driver with it OFF is an error.
- Actual topology: 32 KiB, two ways, compact/banked tags, two MSHRs, two response
  credits, two WB slots, Mixed coherent home, unordered bridge, four AXI read
  credits, 128 KiB backing aperture at `0x80010000`.
- Driver includes `../harness/coherent_cache_home.cpp` unchanged through
  `CACHE_HOME_EMBED`. The existing real DDR mixed model is unchanged.

The parent owns production/configuration, wrapper, emitter and runner edits.
Only this new driver and this document belong to this preparation.

## Preserved checks

The four original actual cache scenarios remain: cold-store candidate barrier
and same-line retry with full/partial store hits and response/refill pressure;
dirty PF, full held C, late Ack, MSHR reuse and direct-demand stale-PF ABA;
1,024-line/eight-word dirty steady stream; actual AXI SLVERR, denied/corrupt PF
drop, faulting demand store, unchanged bytes, DMA backing check and successful
reacquire after error clear. Their checked-store-PF enabled path runs in BOTH
insertion modes. The old disabled branches remain as source history but are
unreachable under this driver's enforced always-ON contract.

The original independent CPU/DMA data and byte-mask model, held CPU/DMA reply
checks, A/source, complete D/sink/E, C/release/Ack, immutable WB generation
history, held C payload and held E sink, dirty probes, actual AXI byte strobes,
and full backing-image cache/home flush all remain active. No protocol responder,
tag/data overwrite, forced hit, synthetic throughput or performance threshold
is added. The original million-cycle instance limit and bounded waits remain.

## Two added authored conflicts

Both scenarios author full physical addresses without consulting DUT tags,
replacement bits or private generated state. With a 16 KiB alias stride:

- X = base + 128, Y = X + stride
- B-next = X + 2 strides, A-next = X + 3 strides
- B-previous = B-next - 128, B-current = B-next - 64

All four target lines map to one two-way set. Real demand misses fill X then Y.
The store-origin case dirties X and Y through ordinary partial stores, then
trains the existing store history with B-previous/B-current full stores. The
initial cold candidate must lose to the existing barrier. A real B-current hit
retry produces B-next PF. In the read-origin case X and Y are clean, partial
setup stores establish B-previous/B-current, and two ordinary reads author the
read-origin PF. Partial setup stores cannot authorize a PF of their own.

The gate holds real coherent D long enough to require a live, acquired B-next
PF owner of the expected origin, records its immutable MSHR generation, and
checks that its actual victim capture is X. Releasing D must result in actual
complete D/E, successful refill/install, owner retirement and resident B-next
plus Y. PF cannot invent a CPU reply or modify the architectural target image.

A real A-next read demand then must choose the following actual full-PA victim:

- Store-origin / insertion OFF: B-next, clean, one C Release beat
- Store-origin / insertion ON: Y, dirty, eight C ReleaseData beats
- Read-origin / either mode: B-next, clean, one C Release beat

A later ordinary B-next byte-masked store must be an actual hit only for the
store-origin MRU case, otherwise an actual miss with real reacquire. The mask
prevents that final store from authoring another PF; this isolates insertion
without disabling authorization or touching DUT state. Useful consumption and
actual Acquire deltas must agree with the admission. Expected changed lanes
are authored explicitly and checked by subsequent real DMA/full-image flush.

Every relevant line receives eight-word DMA reads. Dirty B-next bytes must
produce a real eight-beat dirty probe. A partial DMA write invalidates B-next;
a CPU demand must reacquire, and all eight words are checked again. Final
cache/home flush checks the entire independently initialized backing image.

## Evidence and no free-gain assumption

`STORE_PREFETCH_INSERTION_EVENT` records actual candidate source/expected full
PA, allocation, MSHR generation, full-PA victim capture, successful/error refill,
and CPU admission hit/miss. Only the two new bounded conflicts enable these
verbose events; they do not replace the existing byte/protocol checks.

`STORE_PREFETCH_INSERTION_PHASE` reports actual cycle, AR transaction, R beat,
AW transaction, W beat, B response, C release beat, demand/PF Acquire and dirty
capture deltas for seed, PF install, A-next demand, B-next store, verification
with flush, and the whole case. Full case records include the same real AXI
counts. In particular MRU can move eviction from a clean PF to an alternate
dirty way; the eight-beat release and eventual AW/W cost are retained and
reported. Phase boundaries are observation windows, not a claim that every
writeback is committed within the phase that caused it. Whole-case totals
include DMA and flush and drain all accepted traffic.

These are authored functional cache/home scenarios, not executing-CPU, original
COPY/guest, board, DDR PHY, FPGA timing or production-throughput results.
Every summary explicitly says `performance_qualification=0`.

## Runner acceptance and negative controls

Normal success emits six `STORE_PREFETCH_INSERTION_CASE` records, the retained
`STORE_PREFETCH_INSERTION_STEADY`, two `STORE_PREFETCH_INSERTION_CONFLICT` records
(one for each origin), followed only after both new scenarios' DMA/reacquire/
flush obligations finish by:

`STORE_PREFETCH_INSERTION_TWO_CONFLICT_PASS store_pf=1 store_pf_mru=0|1 store_origin=1 read_origin=1 full_pa_victim=1 later_store_admission=1 dirty_probe_dma=1 reacquire=1 full_flush=1 performance_qualification=0`

The terminal success marker is:

`STORE_PREFETCH_INSERTION_PASS store_pf=1 store_pf_mru=0|1 cases=6 read_origin_stays_lru=1 ...`

The runner must require the mode-matching terminal and two-conflict markers,
and the expected real hit/miss/victim outcomes above; no cycle-speed threshold.
Nonzero exit or missing coverage is failure. No marker is evidence until an
actual model run emits it from the bound sources.

Run each mutation separately, in BOTH insertion modes:

- `--inject-mismatch`: original byte mutation, nonzero with
  `STORE_PREFETCH_INSERTION_FAIL CPU independent byte oracle mismatch`.
- `--inject-wb-prefetch-aba`: original real direct-demand/stale-PF capture must
  emit `STORE_PREFETCH_INSERTION_MUTATION_TRIGGER wb-prefetch-aba`, then fail
  with `WB capture stale-PF ABA origin mismatch`.
- `--inject-insertion-expectation`: flips only the host's authored store-origin
  victim expectation after real A-next capture. Must emit the
  `insertion-expectation origin=store` trigger and fail with
  `A-next full-PA victim disagrees with authored insertion expectation`.
- `--inject-read-origin-mru`: intentionally expects read-origin MRU retention.
  Must reach the real A-next capture, emit the matching `origin=read` trigger,
  and fail with the same full-PA victim oracle diagnostic.

The new mutations test oracle sensitivity; they are explicitly host expectation
mutations, not a claim of a separately built faulty RTL. An untriggered
mutation, unrelated failure, zero exit or terminal PASS is not a passing
negative control.
