# Next architectural checkpoint: commit-authorized physical stores

Design proposal only, 2026-10-09. No implementation or performance gain is claimed.
Finish the paired queue-flow checks and actual executed-CPU six-to-five-cycle
measurement before changing this path.

## New measured reason to investigate

The frozen old-selected all-hit replay now gives 8 KiB/4-pass write kernel
19,529 cycles, 160.018 MiB/s at an assumed 100 MHz. Every measured store has a
two-cycle CPU-start-to-result lifetime. StoreBuffer occupancy reaches one of its
two entries and never fills; start spacing is predominantly four cycles, with
ten-cycle boundaries between the eight-store groups. Therefore increasing the
StoreBuffer by itself does not address the demonstrated supply limitation.

This is separate from the read roof: two actual load owners each remain occupied
for six cycles and can be replaced on completion. The current physical-ingress
experiment targets that read latency without increasing capacity. The user's
broader performance/area goal permits moving either limit after qualification.

## Narrow redesign to evaluate first

Separate proven, committed ordinary physical stores from speculative LSU read
owners. The core already holds prepared store address/data and the StoreBuffer
already has an independent fast-store enqueue port. A new modern registered
commit authorization path can reuse those facts without activating the legacy
`fastBufferedStoreRetire` flag, which is incompatible with selected registered
memory preparation, replay, redirect and retirement profiles.

Possible structure:

1. Keep early address/data preparation and full ROB allocation identity. Cache
   a head-store certificate only after alignment, whole-RAM range, current PMP
   and effective-privilege checks. Virtual, MMIO, uncached and atomic operations
   retain their existing precise serial path.
2. At the exact authorized ROB head, enqueue the prepared physical store into
   the existing guaranteed-success StoreBuffer. Gate on commit enable, absence
   of pending trap/recovery/system exclusion, certificate freshness and available
   capacity. Acceptance is the irrevocable ownership transfer.
3. Produce a registered, full-token store completion through explicit bounded
   arbitration. Do not combinationally retire a newly accepted store, borrow a
   speculative future response, or remove the actual downstream response owner.
4. Keep accepted store ownership independent of ROB-slot reuse until the real
   physical response drains. Fences, PMP/SATP changes, traps and FP/system epochs
   continue to include all queued/in-flight stores in their drain condition.
5. Preserve older-store/younger-load byte ordering and the existing held-direct
   request arbitration. Do not let a newly accepted fast store replace an already
   held request or invalidate a forwarded load's committed-memory version.

This should be implemented as a separate default-off checkpoint, then measured
against the identical new flow-qualified baseline. The useful goal is eliminating
head-store launch/ack/retire bubbles while retaining StoreBuffer depth two, not a
promised throughput figure. A two-entry buffer can become the next real limiter
once stores actually arrive faster; only measure it then.

## Required independent proof before broader use

- Irrevocable stores only at a current, exact full-token head; duplicate accepted
  stores, stale certificate and ROB-index reuse mutations must be rejected.
- Store accept and competing load/system/multiply completion on the same edge;
  completion backpressure and bounded progress; no dropped or duplicated result.
- Recovery/trap/interrupt before acceptance, at acceptance, after acceptance and
  before physical response; accepted stores may drain but may never be canceled.
- PMP locked/unlocked permissions, alignment/range endpoint, MPRV/effective mode,
  virtual fallback, MMIO and atomics; faults remain precise with no write effect.
- Partial-byte stores, overlapping loads, local forwarding, held direct requests,
  StoreBuffer wrap/full/simultaneous response, fences and context drain.
- Real D-cache/coherence effects, dirty lines, DMA probes and LR/SC/AMO exclusion.
- Executed-core architectural checking, independent full-token/event ledger,
  oracle-corruption negatives, and same-ELF hot/stream read/write/copy timings.

Report kernel and actual drain/flush completion separately. Compare register,
LUT, memory and mux structure; do not claim reduced FPGA area or 100 MHz timing
from source counts. A routed check remains an explicit later acceptance gate.
