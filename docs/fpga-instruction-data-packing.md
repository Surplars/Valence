# Instruction-cache data packing

Status: the six corrected-reference storage pairs pass focused GSIM and selected
native memory-geometry checks. Whole-board integration and FPGA mapping/timing are
pending. The existing parallel-way layout remains the constructor default; select
`InstructionLineCache.bankedData` or the focused `--banked-instruction-data` flag.
The independent held-hit snapshot correction (`dec7d8e`) is required in both layouts.

## Equal-capacity geometry

For the selected 512-line, two-way, 32 KiB I-cache:

| Layout | Native data-memory instances | Ports per memory | Read latency |
| --- | --- | --- | --- |
| Reference | 2 × 256 × 512 bits | 1R/1W | 1 cycle |
| Packed | 8 × 512 × 64 bits | 1R/1W | 1 cycle |

Both store exactly 262,144 bits. The selected fixture uses the actual
`0x80200000` base and 2 GiB aperture, with 19-bit compact tags spanning 4 GiB.
Native helper/module/output hashes are bound in
`docs/evidence/fpga-instruction-data-packing-20261008.json`.

This does not claim that the original data was unmapped. The historical I-cache
already used 14 RAMB36 plus two RAMB18. Actual primitive counts, LUTs, routing and
100 MHz setup require a new implementation; no physical savings are claimed here.

A two-word packet enables one 64-bit bank. A four-word packet enables two adjacent
banks. Offset 56 for a four-word packet retains the precise cross-line fallback.
A successful fill writes all eight banks, with the selected way in the address MSB.
The existing fill admission excludes simultaneous new hit reads; the candidate also
asserts that condition rather than relying on undefined RAM collision behavior.

## Behavior and throughput

Twelve models cover selected packet2, packet4, both prefetch widths, a narrow aperture
crossing 4 GiB, and a four-line/full-tag geometry. Each non-prefetch model runs seeds
1/7/31/127 over every resident set, way and packet bank under randomized held offers
and held responses. CPU data is checked from accepted addresses and independent
backing generations, not DUT tag/way/index state. Both prefetch layouts also run the
six held-hit scenarios, including first-stall prefetch installation plus invalidate.
Payload corruption, last-bank-only corruption and broken hit snapshots are rejected.

Every paired log and cycle/traffic metric is identical. The selected packet2 trace
reads 4,096 resident packets in 5,991 cycles for seed1 with its intentional stalls.
The packet4 trace reads 3,584 packets in 5,268 cycles. Unstalled hits retain one-cycle
accepted-to-response latency and initiation interval one. The serial helper still
takes 13 stepping calls for a cold fetch and two for a hot fetch; the latter includes
the request-acceptance call and the response call. Prefetch fixtures both take 81
steps. Replacement/LRU, all eight refill beats, high aliases, above-4-GiB addresses,
permission fallback, failed refills, precise error lanes, held refill replies,
in-flight invalidation and reset remain independently checked.

## Timing tradeoff

Reference native RAM addresses are only `io_fetch_request_bits[13:6]`; tag-derived
way hits qualify read enable and the returned way mux. Packed native RAM addresses
are `{hits_1, io_fetch_request_bits[13:6]}`. Thus the address MSB now depends on the
19-bit asynchronous tag comparison, selected valid bit, aperture-prefix qualification
and invalidation. This is a real address-setup tradeoff, even though the simulation
latency is unchanged. Removing redundant qualification from the address alone would
be a separate, newly tested refinement; it is not part of this frozen receipt.

The source and native geometry establish an inference target, not an FPGA mapping
or routed timing result. Whole-profile CPU/NEMU replay remains an integration gate.
