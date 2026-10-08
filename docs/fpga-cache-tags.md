# FPGA cache-tag storage candidate

`CacheTagConfig(bankedStorage = true)` opts the nonblocking data cache and instruction
cache into per-way asynchronous `Mem` tag banks. The existing register-vector layout
remains the default. Tag width is still controlled independently by `compact`; physical
addresses, permission checks, cache geometry, valid/dirty state, and replacement policy
remain unchanged. The blocking one-MSHR data-cache reference retains register tags.

## Port and ownership contract

For a 512-line, two-way cache, each bank has 256 entries. The data cache uses one
functional read port per way without data prefetch and two with prefetch enabled:

- Primary: a consumed coherence probe, otherwise an active flush scan, otherwise CPU
  demand. CPU requests cannot fire with BVALID. A flush excludes CPU demand. A consumed
  probe excludes eviction capture. The selection uses B.fire, because an unconsumed B
  can coexist with a flush eviction whose metadata must still be read.
- Speculation: the authorized prefetch candidate, independent of the primary port.

A demand or prefetch miss captures its victim tag when reserving a set. Queued eviction
reconstructs the victim address from that tag and the reserved index. No other miss can
reserve that set; a probe can invalidate the victim but cannot replace its tag. Bypass
captures the same information and is an existing full barrier. Flush uses the primary
port because it already owns cache admission.

The tracked-prefetch token uses the slot's valid bit rather than another tag read.
Every replacement invalidates the old slot before a later fill can install a new tag;
the token observes that invalid cycle and clears before slot reuse. A consumed token
and an explicit flush also clear it. A new successful prefetch fill has final priority
when creating its new token.

The instruction cache has demand and speculative ports per way. The speculative port
reads the next demand line when no candidate exists, or the following candidate line
while a candidate exists. A demand may create a candidate only when no candidate
already exists; a candidate can advance only from an existing candidate's accepted
prefetch request. These two consumers are mutually exclusive even when demand and
prefetch activity overlap.

Each way has one tag write port, used only for successful, permitted refill installation.
No tag reset is required: valid bits remain resettable registers. Data arrays remain the
existing synchronous SRAMs. The intended hit contract is still one-cycle latency and
one request per cycle when response credits and SRAM arbitration permit it.

## Evidence and boundaries

Run the bounded paired suite with:

    python simulator/gsim/banked_cache_tags.py --tag <unique-name> --build-run

Without `--build-run` the script reports its planned scope. Every case first runs the
register baseline through the same independent C++ oracle, then the banked candidate.
The suite compares observable outcome/counter logs and includes intentional payload
corruption controls. Cases cover all data-cache sets, both ways, one-way geometry,
full/compact tags, a 4 GiB-crossing aperture, high-address aliases, masked writes,
dirty eviction, probes during held replies, failed refill retry, coordinated reset,
instruction invalidation/fallback, and real cache/home/DMA/AXI integration.

The standalone script records source hashes and emitted memory geometry. These are
structural facts. They do not establish FPGA LUT/FF/BRAM utilization, routed timing,
board DDR behavior, or CPU workload performance. Those remain unmeasured until the
selected integrated profile is built and tested on the authorized FPGA toolchain.

The `!directEviction` prefetch-owner assertion correction is included separately from
the storage change. It prevents a new demand from being mistaken for the stale prefetch
bit of a FREE reused MSHR; it changes verification enable only, not functional hardware.

The first directed result is `docs/evidence/fpga-cache-tags-20261008.json`:
seven baseline/candidate pairs passed with identical driver outputs. The selected
mixed integration retained 40,093 cycles for 1,024 steady replacement lines and
26,587 dirty replacement cycles; this is a latency-neutral storage transformation,
not a throughput gain. The owner-reuse fixture retained 578 cycles, 16 independently
checked writeback beats and 16,384 checked backing words. Randomized contention
extension and integrated CPU checks are separate pending gates.

The runtime-seeded extension also passed: eight seeds, each with 1,024 randomized
CPU operations plus DMA and directed shared-line probe episodes. Baseline and banked
tags have identical cycle, traffic, and p50/p99/maximum response-latency records for
every seed. The oracle checks every completed CPU/DMA reply, every dirty probe,
owner closure, and the entire backing image after flush. CPU and DMA random streams
use disjoint halves; shared-line operations synchronize stores before probing so the
acceptance-time oracle does not impose an invented order on racing writes. Both
variants reject intentional response-data corruption. See
`docs/evidence/fpga-cache-tags-seeded-20261008.json`.

`cache_seeded_stress.py` reuses content-verified emitted RTL, compiles each model object
once, and accepts runtime `--seeds` and `--iterations`. The source-locked replay checkout
can be separate from ongoing implementation work. This is still a module/integration
result, not a CPU benchmark or measured FPGA resource/timing result.

The actual selected 2 GiB, 32 KiB-per-cache board export closes the tag-width census:
both caches contain two 256×19-bit banks. The final reachable native SV has two read
ports and one write port per D tag bank; the selected two-word I profile lowers to
one read and one write port per bank because line prefetch is suppressed. CHIRRTL
initially declared two I reads, so native helper counts are the appropriate final
structural port census. Export-receipt and RTL hashes are recorded in
`docs/evidence/fpga-cache-tags-native-20261008.json`. This does not establish physical
RAM inference, LUT/FF/BRAM counts, or routed slack.
