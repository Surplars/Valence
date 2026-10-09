# Reconstructed actual store-prefetch cache/home gate

## Identity and status

This source was reconstructed on checkpoint
`72d44d90d4a6b9c71046dd363cfb13fce339ec8a` after the earlier workspace was lost.
It is not a hash-verified copy of the earlier final source and inherits no
runtime PASS. No Scala, C++, generated model or GSIM build/run was performed
while preparing these files. Freeze, build and run the new source before
making a functional qualification claim.

The accompanying passive wrapper patch was prepared separately at
`cache-gate-preparation/passive-cache-wrapper.patch` in the recovery directory.
The parent controls its review/application and the coherent source freeze.
It extends the existing `observationStorePrefetch` with passive scalar event
and lifetime fields. Existing field names `allocated`, `allocatedStore`,
`allocatedAddress` and `allocatedSlot` are preserved. Nothing consumes these
new observations to grant permission, choose arbitration or drive a protocol.

## Build contract

Emitter: `ooo.CheckedStorePrefetchCacheGsimMain out 0|1`.
Generated top: `CoherentCacheHomeGsim`.
C++ driver: `cache.cpp`, with explicit `-DCHECKED_STORE_PREFETCH=0|1` matching
the emitter, generated-header and `simulator/gsim/harness` include directories.
The source selects the existing `MIXED_MODEL` / `MIXED_RTL` paths.

Selected topology: 32 KiB, two ways, banked tags, two MSHRs, two CPU response
credits, two writeback slots, actual Mixed coherent home, 128 KiB RAM aperture
at `0x80010000`, four AXI read credits and unordered responses. Read PF stays
enabled in both models; only checked-store PF changes. Posted merge is absent.

`CACHE_HOME_EMBED` includes the original `../harness/coherent_cache_home.cpp`.
No shared-harness edit, copied/disabled byte oracle, synthetic TileLink manager,
mock model or original performance-guest change is part of this gate.

## Preserved independent checks and added history

Every original `Test` check remains active: independently initialized CPU/DMA
bytes and mask merges, CPU/DMA response ownership and held payloads, A/source,
complete D/sink/E, Release/Ack ownership, actual mixed AXI byte strobes, real
DMA probes, and combined cache/home flush against the complete backing image.

The additional observer gives each actual MSHR allocation a fresh host
generation and keeps each captured WB's immutable origin until real Ack.
A same-edge direct demand allocation is entered before victim capture. Expected
WB prefetch classification comes from that new allocation history, never from
a stale `prefetchOwner(wbMshr)` value. Saved address, slot, sent state and PF
classification are checked on every live snapshot. C data is checked against
victim words saved from the independent architectural image, including all
held beats; all held C fields and E sink are stable. A/D/E/refill retain the
original generation even after a newer MSHR generation appears.

GSIM getters are pre-edge observations. Current state is compared against
preceding events before applying the current events. An MSHR retires only when
a later real live-mask sample shows FREE. Two idle tail cycles check the final
accepted event before completion. No private generated wire is read by the new
observer; the unchanged shared Test retains its existing occupancy check.

The actual AXI-fault input and each expected CPU error are authored stimulus.
An additional FIFO checks CPU error outcomes independently of DUT hit/miss.
Actual store access-error delivery and unmodified bytes are established at this
cache DataPort; architectural cause/token/original-VA tval require the separate
executing-CPU test and are not represented by this wrapper.

## Four bounded cases

1. Cold consecutive stores must lose the first candidate to the real demand
   barrier, then a same-line retry must produce actual PF allocation/A.fire.
   Under held D, require full and partial different-set store-hit acceptances.
   Block a resident same-set store, retain that exclusion with held E, exhaust
   the two response credits, then offer hits continuously across E release and
   require rejection on the actual acquire-response/refill cycle. E alone is
   not claimed to exclude unrelated hits. Real DMA checks untouched target and
   updated current-line bytes.
2. Warm both dirty ways of two independent sets. Require dirty store-PF
   capture, held C rejection, all eight ReleaseData beats and full/partial hit
   acceptance after C is sent while Ack remains held. Retire the PF MSHR, then
   reuse the same free slot for a real demand read with direct dirty eviction.
   Its old PF bit is stale, but its new WB must be demand-owned. While that
   foreign WB remains live, independent stores stay blocked even after the
   demand MSHR drains. Old Ack after MSHR reuse, resumed progress, real DMA
   read/partial write/readback and full flush are required.
3. Write 1,024 consecutive lines, eight full-mask words per line: 64 KiB over a
   32 KiB cache. The second 512-line window separately requires ON-mode actual
   PF allocation, dirty capture, complete dirty release, live-PF store-hit
   acceptance and useful consumption. DMA samples both halves, then flush
   checks every backing byte. These are functional store-only counts, not a
   COPY or original-guest throughput result.
4. Select a cold target and set the existing DDR model's read error before PF
   issue. Real AXI SLVERR must yield Mixed-home denied+corrupt, error PF drop
   and E without a CPU reply or target mutation. A subsequent actual demand
   store must fault without modifying bytes. Clear the error: actual DMA must
   read backing without a cache B probe, proving neither failed E installed
   directory ownership. An actual demand store must reacquire and succeed.

Every wait is bounded and the original million-cycle per-instance limit stays
active. Missing required ON coverage fails. OFF permits zero optimization
coverage, but all performed byte, transport, fault and flush checks still apply.
Candidate/allocation/usefulness origin counters distinguish store origin from
read origin and consuming demand kind; no read-origin result is fabricated.

## Output and negative controls

Normal success emits four `CHECKED_STORE_CACHE_CASE` records, one
`CHECKED_STORE_CACHE_STEADY` record and `CHECKED_STORE_CACHE_PASS store_pf=0|1`.
Records say `reconstructed=1`, `executing_cpu=0` and `performance_qualification=0`.
Fixture cycle counts are diagnostics, not production speedup evidence.

- `--inject-mismatch`: the original shared byte-oracle mutation must exit
  nonzero with `CHECKED_STORE_CACHE_FAIL CPU independent byte oracle mismatch`.
- `--inject-wb-prefetch-aba`: ON only. The actual direct-demand/stale-PF capture
  must first emit `CHECKED_STORE_CACHE_MUTATION_TRIGGER wb-prefetch-aba`; its
  intentionally corrupted observed PF classification must then exit nonzero
  with `CHECKED_STORE_CACHE_FAIL WB capture stale-PF ABA origin mismatch`.
  An untriggered mutation, unrelated failure or zero exit is not a pass.

Generic corrupt-only managers, executing CPU/FENCE/SFENCE/PMP/context ordering,
original guest A/B, FPGA timing and board behavior remain outside this gate.
