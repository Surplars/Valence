# Real CPU/cache/home composition gate: design and source preparation

The executed DMA4 qualification, exact source identities, complete parameter
audit and limits are recorded in
[posted-store-board-lineage-qualification.md](posted-store-board-lineage-qualification.md).
The preparation statements below describe the initial source checkpoint.
Its `25a8c3f` model used DMA line transfers OFF with one entry; it is not the
DMA4 qualification. The corrected, independently emitted DMA4 pair uses
`8f9d08a` and the same functional guest bytes qualified in the later host gate.

This is a new independent namespace based on delivery candidate `afe85a27`,
which includes the frozen CPU qualification `e20b658` and the published
default-OFF return-flow source. Its first model-input freeze is `25a8c3f`.
Nothing in this document or its new passive accounting header is a hardware
runtime or performance result. The qualified CPU tree stays frozen. Both posted
and reference controls keep D16, four LSUs, virtual-load precheck, prepared
stores, checked store prefetch/MRU, physical load ingress, older-load retirement,
and previous fetch packets. Prechecked request flow and translated response
empty flow remain OFF. Original benchmark ELF/bin bytes are separately pinned.

## Actual execution and authority chain

Reuse `FpgaNextBoardGsim.build`, `BoardSocGsim`, `BoardSocTop`, and the selected
`MachinePlatform`. The real private cache is connected through its A/C/D/E
channels to `MixedCoherentLineHome`, the real TileLink crossbar and
`TileLinkAxi4Bridge`, then the independently modeled AXI memory. No fixture may
drive posted proof, cache busy, episode activity, retirement or internal ready.
New scalar test-wrapper observations retain actual ROB/head/full-token/PMP,
cache request/proof acceptance, owner generation/cohort/resource events, TileLink
release/ack handshakes, and aggregate CPU/cache flush/drain events.

One shared raw ROM guest first dirties two actual same-set ways, then performs a
third conflicting physical store with masked same-line updates, an ordinary
load, and FENCE.I. The guest and complete initial/final byte image are identical
for OFF and ON. The environment holds an actual AXI B response for the dirty
victim; the ledger must retain the original CPU token and cache owner through
real ReleaseData, AXI W/B, ReleaseAck and final drain. It checks every intermediate
accepted store and all untouched bytes, rather than only a final signature.
Normal completion requires all accepted AXI and coherence responsibility gone.

This gate is required before a performance comparison. The CPU-only and
cache/home-only passes remain separate premises; their conjunction is not an
executed composition. Deliberate functional B stalls are correctness stimulus,
not throughput measurements. Future benchmarks must preserve their existing
guest bytes and fixed host-memory model on both sides.

## Passive bus-efficiency contract

`simulator/gsim/posted_board_lineage/axi_accounting.h` defines a passive edge
sample and an independent accepted-transaction ledger. The observer samples
actual host-driven input values and evaluated DUT output values on the same
tick, before the memory model consumes handshakes. It never changes traffic.

Kernel ROI and flush are separate, contiguous, complete windows whose boundary
PCs/events are identical on the OFF and ON sides. Accounting tracks ownership
outside both windows and records read/write carry-in and carry-out. A final
empty ledger is required after flush. Starting/stopping counters around only a
convenient burst is not allowed.

For each window, AR, AW, R and W have exactly three mutually exclusive cycle
buckets: `valid && ready`, `valid && !ready`, and `!valid`. Each channel's sum
must equal the complete window cycle count. Accepted R wire bytes count eight
bytes per beat, while requested R payload bytes use the original AR transfer
size. Accepted W wire bytes also count eight per beat, while W payload bytes
use the actual WSTRB population count. Read
ownership lasts from AR fire through its actual RLAST fire. Write ownership
lasts from AW fire through its actual B fire, including all W and delayed-B
cycles. Per-cycle occupancy uses responsibility at the beginning of the
sampled edge and reports sum/mean/peak/full histogram with histogram conservation.

Additional counters distinguish read/write simultaneous ownership, same-cycle
R/W fire, read ownership with RVALID absent, R backpressure, an empty read
window, and an entirely empty bus window. No-offer cycles are not merged with
backpressure or with read-latency gaps. AXI ID reuse, RLAST/WLAST, W ordering,
and B responsibility have independent guards. BVALID requires an original AW/W
owner completed before the sampled edge. Completing an old ID and accepting a
new owner for the same ID on one edge preserves both identities.

The reporting must retain raw cycles, useful guest work, total accepted bytes,
and prefetch-generated traffic separately. Increased unused prefetch traffic
cannot count as an efficiency improvement. The existing stress DDR model fences
reads against writes, while the existing benchmark model permits overlap;
their counters must keep those distinct model identities and cannot be combined
into a hardware bandwidth claim. The accounting header's four manual positive
scenarios and 31 mutation rejections passed standalone C++ ASan/UBSan checks;
this is a host-ledger result, not an executing Board result.

## Frozen model and independently bound host

`simulator/gsim/posted_board_lineage/run_board.py bind` binds a clean explicit
HEAD/tree, every tracked source byte, installed Mill/GSIM/clang/firtool digests,
Python, and relevant inherited environment hashes. `models --slot-granted`
emits OFF then ON using the shared actual Board builder, checks actual CPU/cache
ports and owner widths, generates scalar GSIM accessors, and compiles each
generated translation unit into a retained object. No tool setup or make runs.

The later `run --models PATH --models-receipt-sha256 HASH --slot-granted` uses a
new clean host-source binding. It permits only new Board host/runner/docs changes
relative to the model freeze, verifies the complete original artifact inventory,
and copies the exact FIR/header/generated source/object bytes into fresh output
namespaces before host syntax checks and linking. A changed RTL or build file
rejects reuse. The receipt records both source identities; it does not pretend
that different full source inventories were one source.

Runtime executes old-only/OFF and ON using the identical raw ROM bytes and
deterministic initial byte memory. It independently compares guest hashes,
guarded dense byte snapshots, and canonical nonzero sparse DDR word snapshots
over the complete modeled aperture. Missing sparse words are zero; the host
oracle checks the union of every actual and expected key, including writes
outside the dense guard. Full traces, kernel/flush raw metrics, per-case
failures and the two intended token/byte oracle rejections remain in receipts.
All model and case directories must be fresh. Binding and execution must share
one activated shell so execution-environment hashes remain exact.
